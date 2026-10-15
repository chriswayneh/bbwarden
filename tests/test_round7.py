"""Tests for review fixes on 71946fb."""
import pytest

from bbwarden import cli, core
from bbwarden.http import BBWardenError
from bbwarden.model import demo_workspace


class Backend:
    def __init__(self, fail_global=False):
        self.calls, self.fail_global = [], fail_global

    def remove_global(self, user):
        self.calls.append(("global", user))
        if self.fail_global:
            raise BBWardenError("Bitbucket Cloud has no API to remove a workspace owner")

    def remove_user(self, ws, scope, key, user):
        self.calls.append((scope, key))

    def remove_member(self, group, user):
        self.calls.append(("group", group))

    def load_memberships(self, ws, user):
        pass


def ws_root_everywhere():
    ws = demo_workspace()
    ws.repos["api"]["users"]["root"] = "WRITE"
    ws.groups["ops"].append("root")
    return ws


# (1) global step runs last; failure becomes manual, others kept
def test_offboard_global_step_is_last():
    plan = core.offboard(ws_root_everywhere(), "root")
    assert [p["scope"] for p in plan] == ["repo", "group", "global"]


def test_global_failure_becomes_manual(monkeypatch, capsys):
    ws, be = ws_root_everywhere(), Backend(fail_global=True)
    monkeypatch.setattr("bbwarden.cli.get_ws", lambda args, env=None, **kw: (ws, be))
    rc = cli.main(["offboard", "root", "--apply"])
    out = capsys.readouterr().out
    assert rc == 1
    assert be.calls == [("repo", "api"), ("group", "ops"), ("global", "root")]
    assert "root" not in ws.repos["api"]["users"] and "root" not in ws.groups["ops"]
    assert "2 of 3 steps finished" in out and "MANUAL" in out and "no API to remove" in out


# (2)(3) wording and actual level
def test_global_step_wording_and_level():
    ws = demo_workspace()
    ws.admins["root"] = "global:ADMIN"
    step = core.offboard(ws, "root")[-1]
    assert step["action"] == "remove all global permissions" and step["detail"] == "ADMIN"
    assert core.offboard(demo_workspace(), "root")[-1]["detail"] == "SYS_ADMIN"


# (4) OSError without filename; csv path checked before printing
def test_oserror_without_filename(monkeypatch):
    def boom(*a):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(core, "direct", boom)
    with pytest.raises(SystemExit) as e:
        cli.main(["direct", "--demo"])
    assert str(e.value) == "error: No space left on device"


def test_unwritable_csv_checked_before_table(capsys, tmp_path):
    with pytest.raises(SystemExit, match="cannot open"):
        cli.main(["direct", "--demo", "--csv", str(tmp_path / "missing" / "o.csv")])
    assert capsys.readouterr().out == ""


def test_csv_check_leaves_no_file_on_failure(tmp_path, monkeypatch):
    out = tmp_path / "o.csv"
    monkeypatch.setattr(core, "direct", lambda ws: (_ for _ in ()).throw(core.UnknownUser("x")))
    with pytest.raises(SystemExit):
        cli.main(["direct", "--demo", "--csv", str(out)])
    assert not out.exists()


# (5) formula after leading whitespace
@pytest.mark.parametrize("v", [" =1+1", "  @x", " \t+cmd", "\n-1"])
def test_formula_after_whitespace(v):
    assert cli._safe_cell(v).startswith("'")


def test_plain_values_untouched():
    assert cli._safe_cell(" plain") == " plain" and cli._safe_cell("a-b") == "a-b"


# (6) hidden columns are per command, not a global set
def test_no_global_hidden_set_and_key_visible_when_listed():
    assert not hasattr(cli, "HIDDEN")
    assert "KEY" in cli.table([{"key": "k", "x": 1}], ["key", "x"])
    assert "KEY" not in cli.table([{"key": "k", "x": 1}], ["x"])
