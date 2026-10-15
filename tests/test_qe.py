"""Tests for QE findings on harden-live."""
import random

import pytest
from fakehttp import FakeSession, Resp

from bbwarden import __version__, core
from bbwarden.cli import build_parser, get_ws, main
from bbwarden.http import BBWardenError, Http
from bbwarden.live import CloudBackend, DataCenter
from bbwarden.model import RANK, Workspace, demo_workspace

PERMS = list(RANK)


def effective(ws, slug):
    out = {}
    for u, p, _ in core._grants(ws, slug):
        out[u] = max(out.get(u, 0), RANK[p])
    return out


def random_ws(rng):
    users = [f"u{i}" for i in range(rng.randint(1, 7))]
    groups = {f"g{i}": rng.sample(users, rng.randint(0, len(users))) for i in range(rng.randint(0, 4))}
    pick = lambda pool, n: {x: rng.choice(PERMS) for x in rng.sample(pool, min(n, len(pool)))}
    return Workspace(
        users={u: {"active": True} for u in users},
        groups=groups,
        projects={"P": {"users": pick(users, rng.randint(0, 2)), "groups": pick(list(groups), rng.randint(0, 2))}},
        repos={"r": {"project": "P", "users": pick(users, rng.randint(0, 4)),
                     "groups": pick(list(groups), rng.randint(0, 2))}},
    )


# BLOCKER: regroup --apply must never widen access
def test_regroup_never_widens_access_property():
    for seed in range(2000):
        ws = random_ws(random.Random(seed))
        before = effective(ws, "r")
        core.apply_regroup(ws, core.regroup(ws, "r"))
        after = effective(ws, "r")
        for u, rk in after.items():
            assert rk <= before.get(u, 0), f"seed {seed}: {u} went {before.get(u, 0)} -> {rk}"
        for u, rk in before.items():
            assert after.get(u, 0) == rk, f"seed {seed}: {u} lost access {rk} -> {after.get(u, 0)}"


def test_regroup_no_access_user_stays_without_access():
    ws = Workspace(users={"a": {"active": True}, "b": {"active": True}},
                   groups={"g": ["a", "b"]}, projects={"P": {"users": {}, "groups": {}}},
                   repos={"r": {"project": "P", "users": {"a": "READ"}, "groups": {}}})
    plan = core.regroup(ws, "r")
    assert plan[0]["action"] == "manual"
    core.apply_regroup(ws, plan)
    assert "b" not in effective(ws, "r")


# Live mode must not mark every user active
def test_cloud_live_status_is_unknown_not_active():
    page = lambda v: Resp(body={"values": v})
    sess = FakeSession({
        ("GET", "/2.0/workspaces/acme/projects", None): page([]),
        ("GET", "/2.0/repositories/acme", None): page([{"slug": "api", "project": {"key": "C"}}]),
        ("GET", "/2.0/repositories/acme/api/permissions-config/users", None): page(
            [{"user": {"uuid": "{1}", "account_id": "acc1", "nickname": "bob"}, "permission": "read"}]),
        ("GET", "/2.0/repositories/acme/api/permissions-config/groups", None): page([]),
    })
    ws = CloudBackend(Http(sess, "https://api.bitbucket.org"), "acme").load()
    assert ws.users["acc1"]["active"] is None and ws.users["acc1"]["name"] == "bob"
    assert core.who(ws, "api")[0]["flag"] == "UNKNOWN"


def test_dc_unlisted_user_is_unknown():
    page = lambda v: Resp(body={"values": v, "isLastPage": True})
    P = "/rest/api/1.0"
    sess = FakeSession({
        ("GET", f"{P}/projects", None): page([{"key": "C"}]),
        ("GET", f"{P}/projects/C/permissions/users", None): page([]),
        ("GET", f"{P}/projects/C/permissions/groups", None): page([]),
        ("GET", f"{P}/projects/C/repos", None): page([{"slug": "x"}]),
        ("GET", f"{P}/projects/C/repos/x/permissions/users", None): page(
            [{"user": {"name": "ghost"}, "permission": "REPO_READ"}]),
        ("GET", f"{P}/projects/C/repos/x/permissions/groups", None): page([]),
        ("GET", f"{P}/admin/users", None): page([]),
    })
    ws = DataCenter(Http(sess, "https://bb.example.com")).load()
    assert ws.users["ghost"]["active"] is None


# --version
def test_version_flag(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0
    assert capsys.readouterr().out.strip() == f"bbwarden {__version__}"


# Partial --apply failure reports finished steps
class FlakyBackend:
    def __init__(self, fail_on):
        self.calls, self.fail_on = [], fail_on

    def _call(self, *a):
        self.calls.append(a)
        if len(self.calls) == self.fail_on:
            raise BBWardenError("HTTP 500 on DELETE https://bb.example.com/x")

    def remove_user(self, ws, scope, key, user):
        self._call("remove_user", scope, key, user)

    def remove_member(self, group, user):
        self._call("remove_member", group, user)

    def load_memberships(self, ws, user):
        pass

    def grant_group(self, ws, key, group, perm):
        self._call("grant_group", key, group, perm)


def test_partial_apply_reports_finished_steps(monkeypatch, capsys, caplog):
    ws = demo_workspace()
    ws.groups["devs"].append("erin")
    be = FlakyBackend(fail_on=2)
    monkeypatch.setattr("bbwarden.cli.get_ws", lambda args, env=None, **kw: (ws, be))
    with pytest.raises(SystemExit) as e:
        main(["offboard", "erin", "--apply"])
    err = capsys.readouterr().err
    assert "1 of 3 steps finished" in err
    assert "done    remove direct grant erin: repo api" in err
    assert "FAILED  remove direct grant erin: repo infra" in err
    assert "not run remove membership erin: group devs" in err
    assert "error: HTTP 500" in str(e.value)
    assert "erin" not in ws.repos["api"]["users"] and "erin" in ws.repos["infra"]["users"]
    assert any("finished" in r.getMessage() for r in caplog.records)


# Coverage: live CLI setup, idp csv, offboard direct + membership
def test_get_ws_demo_and_live():
    ws, be = get_ws(build_parser().parse_args(["direct", "--demo"]))
    assert be is None and "api" in ws.repos
    env = {"BBWARDEN_URL": "https://bb.example.com", "BBWARDEN_USER": "u", "BBWARDEN_TOKEN": "t"}
    page = lambda v: Resp(body={"values": v, "isLastPage": True})
    sess = FakeSession({("GET", "/rest/api/1.0/projects", None): page([]),
                        ("GET", "/rest/api/1.0/admin/users", None): page([])})
    seen = []
    ws, be = get_ws(build_parser().parse_args(["direct"]), env,
                    session_factory=lambda *a: seen.append(a) or sess)
    assert isinstance(be, DataCenter) and ws.repos == {}
    assert seen == [("https://bb.example.com", "u", "t", False)]


@pytest.mark.parametrize("val,expected", [("true", True), ("1", True), ("YES", True), (" active ", True),
                                          ("false", False), ("0", False), ("no", False)])
def test_load_idp_csv_values(tmp_path, val, expected):
    f = tmp_path / "idp.csv"
    f.write_text(f"user,active\n bob ,{val}\n")
    assert core.load_idp_csv(f) == {"bob": expected}


def test_orphans_cli_idp_csv(tmp_path, capsys):
    f = tmp_path / "idp.csv"
    f.write_text("user,active\nerin,no\n")
    main(["orphans", "--idp", "csv", "--idp-file", str(f), "--demo"])
    out = capsys.readouterr().out
    disabled = [ln for ln in out.splitlines() if ln.endswith("disabled")]
    assert disabled and all("erin" in ln for ln in disabled)


def test_offboard_removes_direct_project_and_repo_grants():
    ws = demo_workspace()
    ws.projects["CORE"]["users"]["erin"] = "READ"
    plan = core.offboard(ws, "erin")
    assert [(p["scope"], p["name"]) for p in plan] == [("project", "CORE"), ("repo", "api"), ("repo", "infra")]
    core.apply_offboard(ws, "erin", plan)
    assert "erin" not in ws.projects["CORE"]["users"]
    assert all("erin" not in r["users"] for r in ws.repos.values())


def test_offboard_removes_group_memberships():
    ws = demo_workspace()
    be = FlakyBackend(fail_on=0)
    done = core.apply_offboard(ws, "alice", core.offboard(ws, "alice"), be)
    assert len(done) == 2
    assert be.calls == [("remove_member", "admins", "alice"), ("remove_member", "devs", "alice")]
    assert all("alice" not in m for m in ws.groups.values())


def test_partial_regroup_apply_raises_with_progress():
    ws = demo_workspace()
    plan = core.regroup(ws, "api")
    with pytest.raises(core.PartialApply) as e:
        core.apply_regroup(ws, plan, FlakyBackend(fail_on=1))
    assert e.value.done == [] and e.value.failed.startswith("grant group")
    assert ws.repos["api"]["users"].get("bob") == "ADMIN"     # direct grant kept when grant fails
