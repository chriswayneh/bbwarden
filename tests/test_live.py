import pytest
from fakehttp import FakeSession, Resp

from bbwarden.cli import main
from bbwarden.http import AuthError, BBWardenError, Http
from bbwarden.live import CloudBackend, backend_from_env, creds_from_env

SECRET = "s3cr3t-token-value"
DC_ENV = {"BBWARDEN_URL": "https://bb.example.com", "BBWARDEN_USER": "svc", "BBWARDEN_TOKEN": SECRET}
F = frozenset


def http(routes, **kw):
    sleeps = []
    h = Http(FakeSession(routes), "https://bb.example.com", sleep=sleeps.append, **kw)
    return h, sleeps


# ---- pagination ----

def test_dc_pagination_follows_next_page_start():
    h, _ = http({
        ("GET", "/things", F()): Resp(body={"values": [1, 2], "isLastPage": False, "nextPageStart": 2}),
        ("GET", "/things", F({("start", 2)})): Resp(body={"values": [3], "isLastPage": False,
                                                          "nextPageStart": 3}),
        ("GET", "/things", F({("start", 3)})): Resp(body={"values": [4], "isLastPage": True}),
    })
    assert list(h.paginate("things")) == [1, 2, 3, 4]


def test_cloud_pagination_follows_next_url():
    h, _ = http({
        ("GET", "/items", None): [Resp(body={"values": ["a"], "next": "https://bb.example.com/items2?page=2"})],
        ("GET", "/items2", None): Resp(body={"values": ["b"]}),
    })
    assert list(h.paginate("items")) == ["a", "b"]


def test_cloud_pagination_stops_on_repeated_next():
    loop = Resp(body={"values": ["x"], "next": "https://bb.example.com/loop?page=2"})
    h, _ = http({("GET", "/loop", None): loop})
    assert list(h.paginate("loop")) == ["x", "x"]


# ---- retry / backoff ----

def test_retry_honors_retry_after_seconds():
    h, sleeps = http({("GET", "/x", None): [Resp(429, headers={"Retry-After": "7"}), Resp(503),
                                             Resp(body={"ok": 1})]}, base_delay=1.0)
    assert h.get("x") == {"ok": 1}
    assert sleeps[0] == 7.0
    assert 2.0 <= sleeps[1] <= 3.0          # exponential: base * 2**1 plus jitter < base


def test_retry_after_http_date_and_cap():
    h, sleeps = http({("GET", "/x", None): [Resp(429, headers={"Retry-After": "Wed, 21 Oct 2099 07:28:00 GMT"}),
                                             Resp(body={})]}, max_delay=30)
    h.get("x")
    assert sleeps == [30]


def test_retry_gives_up():
    h, sleeps = http({("GET", "/x", None): Resp(429)}, max_retries=3, base_delay=0.5)
    with pytest.raises(BBWardenError, match="still rate limited after 3 retries"):
        h.get("x")
    assert len(sleeps) == 3
    assert sleeps[0] < sleeps[1] < sleeps[2]


def test_no_retry_on_other_errors():
    h, sleeps = http({("GET", "/x", None): Resp(500)})
    with pytest.raises(BBWardenError, match="HTTP 500"):
        h.get("x")
    assert sleeps == []


# ---- auth errors ----

@pytest.mark.parametrize("code,needle", [(401, "check BBWARDEN_USER"), (403, "lack permission")])
def test_auth_errors_are_actionable_and_secret_free(code, needle, capsys):
    sess = FakeSession({("GET", "/projects", None): Resp(code)})
    with pytest.raises(SystemExit) as e:
        main(["direct"], env=DC_ENV, session_factory=lambda *a: sess)
    msg = str(e.value)
    assert needle in msg and SECRET not in msg and "access_token" not in msg
    assert SECRET not in capsys.readouterr().err


def test_auth_error_strips_query_string():
    h, _ = http({("GET", "/x", None): Resp(401)})
    with pytest.raises(AuthError) as e:
        h.get(f"x?access_token={SECRET}")
    assert SECRET not in str(e.value)


def test_missing_creds_named_without_values(capsys):
    with pytest.raises(AuthError) as e:
        creds_from_env({"BBWARDEN_URL": "https://bb.example.com", "BBWARDEN_TOKEN": SECRET})
    assert "BBWARDEN_USER" in str(e.value) and SECRET not in str(e.value)
    with pytest.raises(SystemExit) as e:
        main(["direct"], env={})
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "error: missing BBWARDEN_URL" in err and SECRET not in err


def test_plain_http_rejected():
    with pytest.raises(BBWardenError, match="https"):
        creds_from_env({**DC_ENV, "BBWARDEN_URL": "http://bb.example.com"})


def test_cloud_needs_workspace():
    env = {**DC_ENV, "BBWARDEN_URL": "https://bitbucket.org"}
    with pytest.raises(BBWardenError, match="BBWARDEN_WORKSPACE"):
        backend_from_env(env, session_factory=lambda *a: None)


# ---- live backends end to end on mocked HTTP ----

P = "/rest/api/1.0"


def dc_routes():
    page = lambda vals: Resp(body={"values": vals, "isLastPage": True})
    return {
        ("GET", f"{P}/projects", None): page([{"key": "CORE"}]),
        ("GET", f"{P}/projects/CORE/permissions/users", None): page(
            [{"user": {"name": "dave"}, "permission": "PROJECT_WRITE"}]),
        ("GET", f"{P}/projects/CORE/permissions/groups", None): page(
            [{"group": {"name": "devs"}, "permission": "PROJECT_READ"}]),
        ("GET", f"{P}/projects/CORE/repos", None): page([{"slug": "api"}]),
        ("GET", f"{P}/projects/CORE/repos/api/permissions/users", None): page(
            [{"user": {"name": "bob"}, "permission": "REPO_ADMIN"}]),
        ("GET", f"{P}/projects/CORE/repos/api/permissions/groups", None): page([]),
        ("GET", f"{P}/admin/groups/more-members", None): page([{"name": "bob"}]),
        ("GET", f"{P}/admin/users/more-members", None): page([{"name": "devs"}]),
        ("GET", f"{P}/admin/users", None): page([{"name": "bob", "active": True},
                                                {"name": "dave", "active": False}]),
        ("DELETE", f"{P}/projects/CORE/permissions/users", None): Resp(204),
        ("DELETE", f"{P}/projects/CORE/repos/api/permissions/users", None): Resp(204),
        ("PUT", f"{P}/projects/CORE/repos/api/permissions/groups", None): Resp(204),
        ("POST", f"{P}/admin/users/remove-group", None): Resp(200),
    }


def test_dc_who_live(capsys):
    main(["who", "api"], env=DC_ENV, session_factory=lambda *a: FakeSession(dc_routes()))
    out = capsys.readouterr().out
    assert "CORE/api" in out and "DISABLED" in out


def test_dc_regroup_apply_grants_before_removing(capsys):
    sess = FakeSession(dc_routes())
    main(["regroup", "api", "--apply"], env=DC_ENV, session_factory=lambda *a: sess)
    writes = [(m, u.split("/rest")[1], p) for m, u, p, _ in sess.calls if m != "GET"]
    assert writes == [
        ("PUT", "/api/1.0/projects/CORE/repos/api/permissions/groups",
         {"name": "devs", "permission": "REPO_ADMIN"}),
        ("DELETE", "/api/1.0/projects/CORE/repos/api/permissions/users", {"name": "bob"}),
    ]
    assert "APPLIED to Bitbucket" in capsys.readouterr().out


def test_dc_offboard_dry_run_makes_no_writes():
    sess = FakeSession(dc_routes())
    main(["offboard", "bob"], env=DC_ENV, session_factory=lambda *a: sess)
    assert all(m == "GET" for m, *_ in sess.calls)


def test_dc_offboard_apply():
    sess = FakeSession(dc_routes())
    main(["offboard", "bob", "--apply"], env=DC_ENV, session_factory=lambda *a: sess)
    writes = [(m, j) for m, u, p, j in sess.calls if m != "GET"]
    assert ("POST", {"context": "bob", "itemName": "devs"}) in writes
    assert sum(1 for m, _ in writes if m == "DELETE") == 1


def test_cloud_load_and_offboard():
    W = "/2.0"
    page = lambda vals: Resp(body={"values": vals})
    bob = {"uuid": "{b0b}", "account_id": "557058:b0b", "nickname": "bob"}
    sess = FakeSession({
        ("GET", f"{W}/workspaces/acme/projects", None): page([{"key": "CORE"}]),
        ("GET", f"{W}/workspaces/acme/projects/CORE/permissions-config/users", None): page([]),
        ("GET", f"{W}/workspaces/acme/projects/CORE/permissions-config/groups", None): page([]),
        ("GET", f"{W}/repositories/acme", None): page([{"slug": "api", "project": {"key": "CORE"}}]),
        ("GET", f"{W}/repositories/acme/api/permissions-config/users", None): page(
            [{"user": bob, "permission": "write"}]),
        ("GET", f"{W}/repositories/acme/api/permissions-config/groups", None): page([]),
        ("DELETE", f"{W}/repositories/acme/api/permissions-config/users/557058:b0b", None): Resp(204),
    })
    be = CloudBackend(Http(sess, "https://api.bitbucket.org", sleep=lambda s: None), "acme")
    ws = be.load()
    assert ws.repos["api"]["users"] == {"557058:b0b": "WRITE"}
    from bbwarden import core
    user = core.resolve_user(ws, "bob")
    core.apply_offboard(ws, user, core.offboard(ws, user), be)
    assert sess.calls[-1][0] == "DELETE" and sess.calls[-1][1].endswith("/users/557058:b0b")


def test_crowd_orphans_live(capsys):
    crowd = FakeSession({
        ("GET", "/rest/usermanagement/1/user", F({("username", "bob")})): Resp(body={"active": True}),
        ("GET", "/rest/usermanagement/1/user", F({("username", "dave")})): Resp(body={"active": False}),
    })
    env = {**DC_ENV, "CROWD_URL": "https://crowd.example.com/crowd", "CROWD_APP": "app",
           "CROWD_APP_PASSWORD": SECRET}
    main(["orphans", "--idp", "crowd"], env=env, session_factory=lambda *a: FakeSession(dc_routes()),
         crowd_session=lambda: crowd)
    out = capsys.readouterr().out
    assert "dave" in out and "bob" not in out.split("IDP_STATUS")[1]


def test_crowd_missing_creds(capsys):
    with pytest.raises(SystemExit) as e:
        main(["orphans", "--idp", "crowd"], env=DC_ENV,
             session_factory=lambda *a: FakeSession(dc_routes()))
    assert e.value.code == 2
    assert "CROWD_URL" in capsys.readouterr().err


# ---- review fixes ----

def test_next_link_to_other_host_refused():
    h, _ = http({("GET", "/items", None): Resp(body={"values": [1], "next": "https://evil.example.net/x"})})
    with pytest.raises(BBWardenError, match="another host"):
        list(h.paginate("items"))


def test_network_error_is_clean():
    class Boom:
        def request(self, *a, **k):
            raise ConnectionError(f"failed for token {SECRET}")
    with pytest.raises(BBWardenError) as e:
        Http(Boom(), "https://bb.example.com").get("x")
    assert "ConnectionError" in str(e.value) and SECRET not in str(e.value)


def test_unknown_permission_does_not_crash(capsys):
    r = dc_routes()
    r[("GET", f"{P}/projects/CORE/repos/api/permissions/users", None)] = Resp(
        body={"values": [{"user": {"name": "bob"}, "permission": "REPO_CREATE"}], "isLastPage": True})
    main(["direct"], env=DC_ENV, session_factory=lambda *a: FakeSession(r))
    assert "REPO_CREATE" in capsys.readouterr().out


def test_ambiguous_slug():
    from bbwarden import core
    from bbwarden.model import Workspace
    ws = Workspace(repos={"A/x": {"project": "A", "users": {}, "groups": {}},
                          "B/x": {"project": "B", "users": {}, "groups": {}}})
    with pytest.raises(core.AmbiguousRepo):
        core.who(ws, "x")
