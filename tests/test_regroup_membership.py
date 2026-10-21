"""regroup --apply must not drop a direct grant unless the user is still in the
replacement group right before the removal (Codex 2026-10-21)."""

import pytest

from bbwarden import core
from bbwarden.cli import main
from bbwarden.http import BBWardenError
from bbwarden.model import demo_workspace


class Backend:
    """Records calls; group_members answers from a list of snapshots, one per call."""

    def __init__(self, snapshots):
        self.calls, self.snapshots = [], list(snapshots)

    def group_members(self, group):
        self.calls.append(("group_members", group))
        snap = self.snapshots.pop(0) if len(self.snapshots) > 1 else self.snapshots[0]
        if isinstance(snap, Exception):
            raise snap
        return list(snap)

    def grant_group(self, ws, key, group, perm):
        self.calls.append(("grant_group", key, group, perm))

    def remove_user(self, ws, scope, key, user):
        self.calls.append(("remove_user", scope, key, user))


def _bob_removed(be):
    return any(c[0] == "remove_user" and c[-1] == "bob" for c in be.calls)


@pytest.mark.parametrize("already_granted", [False, True], ids=["grant", "no-grant"])
@pytest.mark.parametrize(
    "later",
    [["alice"], BBWardenError("HTTP 503 on GET /groups")],
    ids=["left-group", "lookup-fails"],
)
def test_direct_grant_kept_when_user_not_confirmed_in_group(already_granted, later):
    ws = demo_workspace()
    if already_granted:
        ws.repos["api"]["groups"]["devs"] = "ADMIN"  # grant step makes no call
    plan = core.regroup(ws, "api")
    be = Backend([["alice", "bob"], later])
    if already_granted:
        be = Backend([later])
    core.apply_regroup(ws, plan, be)
    assert not _bob_removed(be)
    assert ws.repos["api"]["users"]["bob"] == "ADMIN"
    assert any("bob" in lab and "skipped" in why for lab, why in ws.manual)


def test_direct_grant_removed_when_still_a_member():
    ws = demo_workspace()
    plan = core.regroup(ws, "api")
    be = Backend([["alice", "bob"]])
    core.apply_regroup(ws, plan, be)
    assert _bob_removed(be) and "bob" not in ws.repos["api"]["users"]


def test_cli_exit_1_and_skip_reported(monkeypatch, capsys):
    ws = demo_workspace()
    be = Backend([["alice", "bob"], ["alice"]])
    monkeypatch.setattr("bbwarden.cli.get_ws", lambda args, env=None, **kw: (ws, be))
    assert main(["regroup", "api", "--apply"]) == 1
    err = capsys.readouterr().err
    assert "MANUAL" in err and "bob" in err and "skipped" in err
    assert not _bob_removed(be)
