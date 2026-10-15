"""Tests for the second independent review of harden-live."""

from pathlib import Path

import pytest
from fakehttp import FakeSession, Resp

from bbwarden import core
from bbwarden.cli import main
from bbwarden.http import BBWardenError, Http
from bbwarden.live import CloudBackend, backend_from_env, creds_from_env
from bbwarden.model import Workspace

ENV = {"BBWARDEN_USER": "u", "BBWARDEN_TOKEN": "t", "BBWARDEN_WORKSPACE": "acme"}


def kind(url):
    seen = []
    backend_from_env(
        {**ENV, "BBWARDEN_URL": url}, session_factory=lambda *a: seen.append(a) or None
    )
    return seen[0][3]


# 1 Cloud detection by exact hostname
@pytest.mark.parametrize(
    "url,cloud",
    [
        ("https://bitbucket.org", True),
        ("https://api.bitbucket.org/", True),
        ("https://BITBUCKET.ORG/x", True),
        ("https://bitbucket.orgname.com", False),
        ("https://evil.com/bitbucket.org", False),
        ("https://bitbucket.org.evil.com", False),
        ("https://git.bitbucket.org", False),
    ],
)
def test_cloud_detection_exact_host(url, cloud):
    assert kind(url) is cloud


# 2 next link must match scheme, host and port
@pytest.mark.parametrize(
    "nxt",
    [
        "http://bb.example.com/p2",
        "https://bb.example.com:8443/p2",
        "https://other.example.com/p2",
    ],
)
def test_next_link_origin_mismatch_refused(nxt):
    h = Http(
        FakeSession({("GET", "/p1", None): Resp(body={"values": [1], "next": nxt})}),
        "https://bb.example.com",
        sleep=lambda s: None,
    )
    with pytest.raises(BBWardenError, match="another host"):
        list(h.paginate("p1"))


def test_next_link_default_port_ok():
    h = Http(
        FakeSession(
            {
                ("GET", "/p1", None): Resp(
                    body={"values": [1], "next": "https://bb.example.com:443/p2"}
                ),
                ("GET", "/p2", None): Resp(body={"values": [2]}),
            }
        ),
        "https://bb.example.com",
        sleep=lambda s: None,
    )
    assert list(h.paginate("p1")) == [1, 2]


# 3 Cloud users keyed by account_id
def cloud_sess(extra=None):
    page = lambda v: Resp(body={"values": v})
    a = {"uuid": "{a}", "account_id": "111", "nickname": "sam"}
    b = {"uuid": "{b}", "account_id": "222", "nickname": "sam"}
    r = {
        ("GET", "/2.0/workspaces/acme/projects", None): page([]),
        ("GET", "/2.0/repositories/acme", None): page(
            [{"slug": "api", "project": {"key": "C"}}]
        ),
        ("GET", "/2.0/repositories/acme/api/permissions-config/users", None): page(
            [{"user": a, "permission": "write"}, {"user": b, "permission": "read"}]
        ),
        ("GET", "/2.0/repositories/acme/api/permissions-config/groups", None): page(
            [{"group": {"slug": "devs"}, "permission": "read"}]
        ),
        ("GET", "/1.0/groups/acme/devs/members", None): Resp(body=[b]),
        ("GET", "/1.0/groups/acme", None): Resp(
            body=[{"slug": "devs", "members": [b]}, {"slug": "idle", "members": [b]}]
        ),
        (
            "DELETE",
            "/2.0/repositories/acme/api/permissions-config/users/222",
            None,
        ): Resp(204),
        ("DELETE", "/1.0/groups/acme/devs/members/{b}", None): Resp(204),
        ("DELETE", "/1.0/groups/acme/idle/members/{b}", None): Resp(204),
    }
    r.update(extra or {})
    return FakeSession(r)


def cloud_backend(sess):
    return CloudBackend(
        Http(sess, "https://api.bitbucket.org", sleep=lambda s: None), "acme"
    )


def test_cloud_duplicate_nicknames_do_not_collide():
    ws = cloud_backend(cloud_sess()).load()
    assert ws.repos["api"]["users"] == {"111": "WRITE", "222": "READ"}
    assert {r["user"] for r in core.who(ws, "api")} == {"sam (111)", "sam (222)"}


def test_cloud_ambiguous_offboard_refused(monkeypatch):
    sess = cloud_sess()
    be = cloud_backend(sess)
    ws = be.load()
    monkeypatch.setattr("bbwarden.cli.get_ws", lambda args, env=None, **kw: (ws, be))
    with pytest.raises(SystemExit, match="ambiguous user sam: 111, 222"):
        main(["offboard", "sam", "--apply"])
    assert all(m == "GET" for m, *_ in sess.calls)


def test_cloud_offboard_by_account_id_hits_right_person(monkeypatch):
    sess = cloud_sess()
    be = cloud_backend(sess)
    ws = be.load()
    monkeypatch.setattr("bbwarden.cli.get_ws", lambda args, env=None, **kw: (ws, be))
    main(["offboard", "222", "--apply"])
    deletes = sorted(u.split("acme/")[1] for m, u, *_ in sess.calls if m == "DELETE")
    assert deletes == [
        "api/permissions-config/users/222",
        "devs/members/{b}",
        "idle/members/{b}",
    ]


def test_cloud_unknown_user_fails_instead_of_guessing():
    be = cloud_backend(cloud_sess())
    be.load()
    with pytest.raises(BBWardenError, match="unknown Cloud user"):
        be.remove_member("devs", "nobody")


# 4 superseded by secure-defaults: http needs --insecure for every host (tests/test_secure.py)
@pytest.mark.parametrize(
    "url", ["http://localhost.evil.com", "http://localhostx", "http://example.com"]
)
def test_http_refused_by_default(url):
    with pytest.raises(BBWardenError, match="https"):
        creds_from_env({**ENV, "BBWARDEN_URL": url})


# 5 unknown permission is manual in regroup
def test_regroup_unknown_permission_is_manual():
    ws = Workspace(
        users={"a": {"active": True}},
        groups={"g": ["a"]},
        projects={"P": {"users": {}, "groups": {}}},
        repos={"r": {"project": "P", "users": {"a": "REPO_CREATE"}, "groups": {}}},
    )
    plan = core.regroup(ws, "r")
    assert plan[0]["action"] == "manual" and "unknown permission" in plan[0]["detail"]

    class Rec:
        def __init__(self):
            self.calls = []

        def grant_group(self, *a):
            self.calls.append(a)

        def remove_user(self, *a):
            self.calls.append(a)

    rec = Rec()
    core.apply_regroup(ws, plan, rec)
    assert rec.calls == []


# 6 offboard loads all memberships (DC)
def test_dc_offboard_loads_all_memberships(monkeypatch):
    page = lambda v: Resp(body={"values": v, "isLastPage": True})
    P = "/rest/api/1.0"
    sess = FakeSession(
        {
            ("GET", f"{P}/projects", None): page([]),
            ("GET", f"{P}/admin/users", None): page([]),
            ("GET", f"{P}/admin/users/more-members", None): page(
                [{"name": "unused-grp"}]
            ),
            ("POST", f"{P}/admin/users/remove-group", None): Resp(200),
        }
    )
    main(
        ["offboard", "zed", "--apply"],
        env={**ENV, "BBWARDEN_URL": "https://bb.example.com"},
        session_factory=lambda *a: sess,
    )
    assert ("POST", {"context": "zed", "itemName": "unused-grp"}) in [
        (m, j) for m, u, p, j in sess.calls
    ]


# 7 --skip-memberships
def test_offboard_skip_memberships(capsys):
    main(["offboard", "alice", "--demo", "--skip-memberships"])
    out = capsys.readouterr().out
    assert "group" not in out.split("DRY RUN")[0].lower().replace("(no results)", "")


# 8 no retry on POST
def test_post_not_retried():
    sleeps = []
    sess = FakeSession({("POST", "/x", None): [Resp(503), Resp(200)]})
    h = Http(sess, "https://bb.example.com", sleep=sleeps.append)
    with pytest.raises(BBWardenError, match="503"):
        h.request("POST", "x")
    assert sleeps == [] and len(sess.calls) == 1


def test_put_and_delete_retried():
    for m in ("PUT", "DELETE"):
        sleeps = []
        h = Http(
            FakeSession({(m, "/x", None): [Resp(429), Resp(204)]}),
            "https://bb.example.com",
            sleep=sleeps.append,
        )
        assert h.request(m, "x").status_code == 204 and len(sleeps) == 1


# 9 non-JSON response
def test_non_json_response_clean_error():
    class Html(Resp):
        def json(self):
            raise ValueError("Expecting value: <html>secret page</html>")

    h = Http(FakeSession({("GET", "/x", None): Html(200)}), "https://bb.example.com")
    with pytest.raises(BBWardenError) as e:
        h.get("x")
    assert (
        "200" in str(e.value)
        and "not JSON" in str(e.value)
        and "secret" not in str(e.value)
    )


# 10 Cloud 1.0 groups call mocked
def test_cloud_legacy_groups_members_call():
    sess = cloud_sess()
    ws = cloud_backend(sess).load()
    assert ws.groups["devs"] == ["222"]
    assert any(u.endswith("/1.0/groups/acme/devs/members") for m, u, *_ in sess.calls)


def test_readme_notes():
    s = (Path(__file__).resolve().parent.parent / "README.md").read_text()
    assert "legacy" in s and "--skip-memberships" in s and "read-only" in s
