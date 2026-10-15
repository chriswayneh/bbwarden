"""Codex runner-2026-10-15 on dfd0b68: 7. Ctrl-C during --apply reports what finished."""

import pytest

from bbwarden import cli
from bbwarden.model import demo_workspace

# 7. Ctrl-C during --apply reports what finished


class InterruptSecond:
    def __init__(self):
        self.calls = 0

    def remove_user(self, ws, scope, key, user):
        self.calls += 1
        if self.calls == 2:
            raise KeyboardInterrupt

    def remove_member(self, group, user):
        pass

    def remove_global(self, user):
        pass

    def load_memberships(self, ws, user):
        pass


def test_f7_ctrl_c_during_apply_reports_progress(monkeypatch, capsys):
    ws = demo_workspace()
    ws.repos["web"]["users"]["dave"] = "WRITE"
    ws.groups.setdefault("ops", []).append("dave")  # a step after the interrupt
    monkeypatch.setattr(
        cli, "get_ws", lambda args, env=None, **kw: (ws, InterruptSecond())
    )
    with pytest.raises(SystemExit) as e:
        cli.main(["offboard", "dave", "--apply"])
    assert e.value.code == 130
    err = capsys.readouterr().err
    assert "INTERRUPTED" in err and "  done    " in err and "not run" in err
