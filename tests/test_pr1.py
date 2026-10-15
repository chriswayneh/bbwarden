"""Tests for QE minor fixes on PR #1."""
import re
from pathlib import Path

import pytest
from fakehttp import FakeSession, Resp

from bbwarden import __version__, core
from bbwarden.http import BBWardenError, Http
from bbwarden.live import CloudBackend, crowd_status
from bbwarden.model import Workspace

ROOT = Path(__file__).resolve().parent.parent


def cloud_ws():
    return Workspace(
        users={"111": {"active": None, "name": "sam"}, "222": {"active": None, "name": "kim"}},
        groups={"devs": ["111", "222"]},
        projects={"C": {"users": {}, "groups": {}}},
        repos={"api": {"project": "C", "users": {"111": "READ"}, "groups": {"devs": "READ"}}})


# (a) missing 'members' is an error, not an empty group
def test_cloud_load_memberships_missing_members_raises():
    sess = FakeSession({("GET", "/1.0/groups/acme", None): Resp(body=[{"slug": "devs"}])})
    be = CloudBackend(Http(sess, "https://api.bitbucket.org"), "acme")
    with pytest.raises(BBWardenError, match="no member list for group devs"):
        be.load_memberships(Workspace(), "111")


# (b) status matching: key first, then display name; README says so
def test_orphans_status_matching_key_then_name():
    ws = cloud_ws()
    assert {r["user"] for r in core.orphans(ws, {"sam": False})} == {"sam (111)"}
    assert {r["user"] for r in core.orphans(ws, {"111": False})} == {"sam (111)"}
    assert core.orphans(ws, {"111": True, "sam": False}) == []      # key wins over name


def test_readme_describes_status_matching():
    s = (ROOT / "README.md").read_text()
    assert "matched by user key first" in s and "nickname" in s


# (c) regroup plan text uses label()
def test_regroup_plan_uses_label():
    ws = cloud_ws()
    ws.groups["solo"] = ["111"]
    plan = core.regroup(ws, "api")
    assert plan[0]["user"] == "sam (111)"
    assert plan[0]["key"] == "111"


def test_regroup_apply_still_uses_key():
    ws = cloud_ws()
    ws.groups["solo"] = ["111"]
    core.apply_regroup(ws, core.regroup(ws, "api"))
    assert ws.repos["api"]["users"] == {}


# (d) resolve_user rejects unknown names
def test_resolve_user_unknown_raises():
    with pytest.raises(core.UnknownUser, match="unknown user nobody"):
        core.resolve_user(cloud_ws(), "nobody")
    assert core.resolve_user(cloud_ws(), "kim") == "222"


# (e) Crowd 404 and other-error branches
def test_crowd_404_is_disabled():
    s = FakeSession({("GET", "/rest/usermanagement/1/user", None): Resp(404)})
    assert crowd_status(Http(s, "https://crowd.example.com"), ["gone"]) == {"gone": False}


def test_crowd_other_error_raises():
    s = FakeSession({("GET", "/rest/usermanagement/1/user", None): Resp(500)})
    with pytest.raises(BBWardenError, match="HTTP 500"):
        crowd_status(Http(s, "https://crowd.example.com"), ["x"])


# (f) version 0.2.0 everywhere plus changelog
def test_version_consistent():
    assert __version__ == "0.2.0"
    py = (ROOT / "pyproject.toml").read_text()
    assert 'version = {attr = "bbwarden.__version__"}' in py and "0.1.0" not in py
    assert "bbwarden 0.2.0" in (ROOT / "README.md").read_text()
    assert re.search(r"^## \[0\.2\.0\]", (ROOT / "CHANGELOG.md").read_text(), re.MULTILINE)


# (g) nosec on jitter
def test_jitter_has_nosec_reason():
    line = next(x for x in (ROOT / "src/bbwarden/http.py").read_text().splitlines() if "random.uniform" in x)
    assert re.search(r"# nosec B311 .*\w{4,}", line)


# review on 7103107: hidden key column, DC typo raises UnknownUser
def test_regroup_table_and_csv_hide_key(tmp_path, capsys):
    from bbwarden.cli import main
    out = tmp_path / "r.csv"
    main(["regroup", "api", "--demo", "--csv", str(out)])
    header = capsys.readouterr().out.splitlines()[0].split()
    assert header == ["REPO", "USER", "ACTION", "GROUP", "DETAIL"]
    assert out.read_text().splitlines()[0] == "repo,user,action,group,detail"
    assert core.regroup(core_demo(), "api")[0]["key"] == "bob"


def core_demo():
    from bbwarden.model import demo_workspace
    return demo_workspace()


def test_readme_samples_match_real_output():
    import subprocess
    import sys
    s = (ROOT / "README.md").read_text()
    for cmd in ["who api", "direct", "orphans --idp crowd", "regroup api", "offboard dave"]:
        out = subprocess.run([sys.executable, "-m", "bbwarden.cli", *cmd.split(), "--demo"],
                             capture_output=True, text=True, check=True).stdout
        assert f"$ bbwarden {cmd} --demo\n{out}```" in s, cmd


def test_dc_typo_user_raises_unknown(monkeypatch):
    from bbwarden.cli import main
    from bbwarden.live import DataCenter
    page = lambda v: Resp(body={"values": v, "isLastPage": True})
    P = "/rest/api/1.0"
    sess = FakeSession({
        ("GET", f"{P}/projects", None): page([]),
        ("GET", f"{P}/admin/users", None): page([]),
        ("GET", f"{P}/admin/users/more-members", None): page([]),
    })
    be = DataCenter(Http(sess, "https://bb.example.com"))
    ws = be.load()
    be.load_memberships(ws, "zedd")
    assert "zedd" not in ws.users
    monkeypatch.setattr("bbwarden.cli.get_ws", lambda args, env=None, **kw: (ws, be))
    with pytest.raises(SystemExit, match="unknown user zedd"):
        main(["offboard", "zedd", "--apply"])
    assert all(m == "GET" for m, *_ in sess.calls)
