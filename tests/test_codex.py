"""Tests for the Codex read-only review of main, checked against harden-live."""
import pytest
from fakehttp import FakeSession, Resp

from bbwarden import core
from bbwarden.cli import main
from bbwarden.http import Http
from bbwarden.live import CloudBackend, DataCenter
from bbwarden.model import Workspace, demo_workspace

P = "/rest/api/1.0"
dcpage = lambda v: Resp(body={"values": v, "isLastPage": True})
cpage = lambda v: Resp(body={"values": v})


def dc(extra=None, projects=None):
    projects = projects or [{"key": "ONE"}]
    r = {("GET", f"{P}/projects", None): dcpage(projects),
         ("GET", f"{P}/admin/users", None): dcpage([]),
         ("GET", f"{P}/admin/groups/more-members", None): dcpage([])}
    for p in projects:
        k = p["key"]
        r[("GET", f"{P}/projects/{k}/permissions/users", None)] = dcpage([])
        r[("GET", f"{P}/projects/{k}/permissions/groups", None)] = dcpage([])
        r[("GET", f"{P}/projects/{k}/repos", None)] = dcpage([{"slug": "api", "public": k == "TWO"}])
        r[("GET", f"{P}/projects/{k}/repos/api/permissions/users", None)] = dcpage(
            [{"user": {"name": f"u{k}"}, "permission": "REPO_WRITE"}])
        r[("GET", f"{P}/projects/{k}/repos/api/permissions/groups", None)] = dcpage([])
    r.update(extra or {})
    return DataCenter(Http(FakeSession(r), "https://bb.example.com", sleep=lambda s: None))


# 1 cross-project slug collision (guard)
def test_dc_same_slug_in_two_projects_kept_apart():
    ws = dc(projects=[{"key": "ONE"}, {"key": "TWO"}]).load()
    assert set(ws.repos) == {"ONE/api", "TWO/api"}
    with pytest.raises(core.AmbiguousRepo):
        core.who(ws, "api")
    assert next(r["user"] for r in core.who(ws, "ONE/api")) == "uONE"


# 4 global admins and public repos
def test_demo_who_includes_global_admin_and_public():
    rows = core.who(demo_workspace(), "web")
    by = {r["user"]: r for r in rows}
    assert by["root"]["effective"] == "ADMIN" and "global:SYS_ADMIN" in by["root"]["sources"]
    assert by["(anyone)"]["sources"] == "public" and by["(anyone)"]["flag"] == "PUBLIC"


def test_dc_loads_global_admins_and_public():
    be = dc({("GET", f"{P}/admin/permissions/users", None): dcpage(
                [{"user": {"name": "root"}, "permission": "SYS_ADMIN"},
                 {"user": {"name": "lic"}, "permission": "LICENSED_USER"}]),
             ("GET", f"{P}/admin/permissions/groups", None): dcpage(
                [{"group": {"name": "sysadmins"}, "permission": "ADMIN"}])},
            projects=[{"key": "TWO"}])
    ws = be.load()
    assert ws.admins == {"root": "global:SYS_ADMIN"} and ws.admin_groups == {"sysadmins": "global:ADMIN"}
    assert ws.repos["TWO/api"]["public"] is True
    assert ws.notes == []


def test_dc_global_admins_forbidden_is_flagged(capsys):
    be = dc({("GET", f"{P}/admin/permissions/users", None): Resp(403)})
    ws = be.load()
    assert any("global" in n for n in ws.notes)


def test_cloud_workspace_owners_and_public():
    sess = FakeSession({
        ("GET", "/2.0/workspaces/acme/permissions", None): cpage(
            [{"user": {"uuid": "{o}", "account_id": "own1", "nickname": "olga"}, "permission": "owner"},
             {"user": {"uuid": "{m}", "account_id": "mem1", "nickname": "mo"}, "permission": "member"}]),
        ("GET", "/2.0/workspaces/acme/projects", None): cpage([]),
        ("GET", "/2.0/repositories/acme", None): cpage([{"slug": "site", "is_private": False}]),
        ("GET", "/2.0/repositories/acme/site/permissions-config/users", None): cpage([]),
        ("GET", "/2.0/repositories/acme/site/permissions-config/groups", None): cpage([]),
    })
    ws = CloudBackend(Http(sess, "https://api.bitbucket.org"), "acme").load()
    assert ws.admins == {"own1": "workspace:owner"}
    rows = {r["user"]: r for r in core.who(ws, "site")}
    assert rows["olga (own1)"]["effective"] == "ADMIN" and "(anyone)" in rows


def test_offboard_plans_global_admin_removal():
    ws = demo_workspace()
    plan = core.offboard(ws, "root")
    assert plan == [{"scope": "global", "name": "SYS_ADMIN", "action": "remove global permission",
                     "detail": "ADMIN"}]
    core.apply_offboard(ws, "root", plan)
    assert "root" not in ws.admins


# 7 regroup wording when only granted groups are known
def test_regroup_manual_wording_is_honest():
    plan = {p["key"]: p for p in core.regroup(demo_workspace(), "api")}
    assert "no granted group contains" in plan["erin"]["detail"]


# 8 group names with spaces (guard)
def test_regroup_group_with_space():
    ws = Workspace(users={"a": {"active": True}}, groups={"team ops": ["a"]},
                   projects={"P": {"users": {}, "groups": {}}},
                   repos={"r": {"project": "P", "users": {"a": "WRITE"}, "groups": {}}})
    core.apply_regroup(ws, core.regroup(ws, "r"))
    assert ws.repos["r"]["groups"] == {"team ops": "WRITE"} and ws.repos["r"]["users"] == {}


# 9 CSV formula injection
@pytest.mark.parametrize("bad", ["=1+1", "+cmd", "-2", "@SUM(A1)", "\tx", "\rx"])
def test_csv_neutralizes_formulas(tmp_path, bad):
    from bbwarden.cli import write_csv
    out = tmp_path / "o.csv"
    write_csv([{"user": bad, "x": "ok"}], out, ["user", "x"])
    cell = out.read_text().splitlines()[1]
    assert cell.startswith(("'", "\"'"))


# 10 strict IdP CSV
@pytest.mark.parametrize("body,msg", [
    ("user,active\nbob,tru\n", "line 2: active must be"),
    ("user,active\nbob,\n", "line 2: active must be"),
    ("user,active\n,true\n", "line 2: empty user"),
    ("user,active\nbob,true\nbob,false\n", "line 3: duplicate user bob"),
    ("name,enabled\nbob,true\n", "columns user,active"),
])
def test_idp_csv_rejects_bad_rows(tmp_path, body, msg):
    f = tmp_path / "idp.csv"
    f.write_text(body)
    with pytest.raises(core.BadIdpFile, match=msg):
        core.load_idp_csv(f)


# 11 identities missing from the IdP are reported
def test_orphans_reports_missing_identities(tmp_path):
    rows = core.orphans(demo_workspace(), {"erin": False, "alice": True})
    st = {(r["repo"], r["user"]): r["idp_status"] for r in rows}
    assert st[("api", "erin")] == "disabled"
    assert st[("api", "bob")] == "missing"


# 12 file errors are clean, not tracebacks
def test_missing_idp_file_clean_error():
    with pytest.raises(SystemExit, match="error: cannot open .*nope.csv"):
        main(["orphans", "--idp", "csv", "--idp-file", "/nonexistent/nope.csv", "--demo"])


def test_unwritable_csv_clean_error():
    with pytest.raises(SystemExit, match="error: cannot open"):
        main(["direct", "--demo", "--csv", "/nonexistent/dir/o.csv"])


# 16 empty CSV still has a header
def test_empty_csv_has_header(tmp_path):
    out = tmp_path / "o.csv"
    main(["offboard", "carol", "--demo", "--skip-memberships", "--csv", str(out)])
    assert out.read_text().splitlines() == ["scope,name,action,detail"]
