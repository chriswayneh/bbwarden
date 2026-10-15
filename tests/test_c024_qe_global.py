"""QE round on PR #12 (d584660): special --csv targets, Ctrl-C in the global step,
pagination flags and the CSV writer's error paths."""

import os
from pathlib import Path

import pytest

from bbwarden import cli
from bbwarden.model import demo_workspace

ROOT = Path(__file__).resolve().parent.parent
posix = pytest.mark.skipif(os.name == "nt", reason="POSIX special files")
ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src")}


# 2. Ctrl-C in the global offboard step


class InterruptGlobal:
    def remove_user(self, ws, scope, key, user):
        pass

    def remove_member(self, group, user):
        pass

    def remove_global(self, user):
        raise KeyboardInterrupt

    def load_memberships(self, ws, user):
        pass


def test_ctrl_c_in_global_step_exit_130(monkeypatch, capsys):
    ws = demo_workspace()
    ws.admins["dave"] = "global:SYS_ADMIN"
    monkeypatch.setattr(
        cli, "get_ws", lambda args, env=None, **kw: (ws, InterruptGlobal())
    )
    with pytest.raises(SystemExit) as e:
        cli.main(["offboard", "dave", "--apply"])
    assert e.value.code == 130
    err = capsys.readouterr().err
    assert "INTERRUPTED" in err and "global" in err and "  done    " in err
