"""Tests for review fixes on 666260e."""

import pytest

from bbwarden import cli, core, live
from bbwarden.http import AuthError, BBWardenError, ManualStep
from bbwarden.model import demo_workspace


class Backend:
    def __init__(self, fail_regular=False, global_exc=None):
        self.calls, self.fail_regular, self.global_exc = [], fail_regular, global_exc

    def remove_global(self, user):
        self.calls.append(("global", user))
        if self.global_exc:
            raise self.global_exc

    def remove_user(self, ws, scope, key, user):
        self.calls.append((scope, key))
        if self.fail_regular:
            raise BBWardenError("HTTP 500 on DELETE https://bb.example.com/x")

    def remove_member(self, group, user):
        self.calls.append(("group", group))

    def load_memberships(self, ws, user):
        pass


def ws_root():
    ws = demo_workspace()
    ws.repos["api"]["users"]["root"] = "WRITE"
    return ws


def run(monkeypatch, be, ws=None):
    ws = ws or ws_root()
    monkeypatch.setattr("bbwarden.cli.get_ws", lambda args, env=None, **kw: (ws, be))
    return ws


def test_partial_failure_lists_global_step_as_not_run():
    ws = ws_root()
    with pytest.raises(core.PartialApply) as e:
        core.apply_offboard(
            ws, "root", core.offboard(ws, "root"), Backend(fail_regular=True)
        )
    assert any("remove all global permissions" in p for p in e.value.pending)


def test_cli_partial_failure_prints_global_not_run(monkeypatch, capsys):
    run(monkeypatch, Backend(fail_regular=True))
    with pytest.raises(SystemExit):
        cli.main(["offboard", "root", "--apply"])
    err = capsys.readouterr().err
    assert (
        "0 of 2 steps finished" in err
        and "not run remove all global permissions" in err
    )


def test_cloud_remove_global_raises_manualstep():
    with pytest.raises(ManualStep):
        live.CloudBackend(None, "acme").remove_global("x")


@pytest.mark.parametrize(
    "exc",
    [
        AuthError("403 Forbidden on DELETE x", 403),
        BBWardenError("HTTP 503 on DELETE x", 503),
        BBWardenError("network error on DELETE x: ConnectionError"),
    ],
)
def test_other_global_errors_are_partial_failures(monkeypatch, capsys, exc):
    ws = run(monkeypatch, Backend(global_exc=exc))
    with pytest.raises(SystemExit):
        cli.main(["offboard", "root", "--apply"])
    err = capsys.readouterr().err
    assert (
        "1 of 2 steps finished" in err
        and "FAILED  remove all global permissions" in err
    )
    assert ws.manual == []


def test_manual_summary_on_stderr(monkeypatch, capsys):
    run(
        monkeypatch,
        Backend(global_exc=live.ManualStep("no API to remove a workspace owner")),
    )
    assert cli.main(["offboard", "root", "--apply"]) == 1
    cap = capsys.readouterr()
    assert "MANUAL" in cap.err and "1 of 2 steps finished" in cap.err
    assert "MANUAL" not in cap.out
