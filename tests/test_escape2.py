"""Review of d72111d: log line forging, backslash ambiguity, line/paragraph separators and
unassigned/private-use code points, display-width alignment, argparse errors."""

import logging

import pytest
from test_round8 import Backend, ws_root

from bbwarden import cli, core

FORGE = "evil\nbbwarden: ERROR forged"


@pytest.mark.parametrize("name", [FORGE, "evil\rbbwarden: ERROR forged"])
def test_formatter_escapes_newlines_in_args(name):
    f = cli.EscapingFormatter("bbwarden: %(levelname)s %(message)s")
    rec = logging.LogRecord(
        "bbwarden", logging.ERROR, "", 0, "step %r: %s", (1, name), None
    )
    out = f.format(rec)
    assert (
        "\n" not in out and "\r" not in out and out.startswith("bbwarden: ERROR step 1")
    )


def test_formatter_keeps_traceback_lines():
    f = cli.EscapingFormatter("%(message)s")
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        rec = logging.LogRecord(
            "x", logging.ERROR, "", 0, "m %s", (FORGE,), sys.exc_info()
        )
    out = f.format(rec)
    assert out.splitlines()[0] == "m evil\\x0abbwarden: ERROR forged"
    assert "Traceback" in out


class FailSecond(Backend):
    def remove_user(self, ws, scope, key, user):
        self.calls.append((scope, key))
        if len(self.calls) > 1:
            raise core.BBWardenError("HTTP 500")


def test_apply_log_through_logger_not_forged(capsys):
    """Real path: core logs 'finished: <label>', and the label carries the user name."""
    ws = ws_root()
    ws.repos["api"]["users"][FORGE] = "WRITE"
    ws.repos["web"]["users"][FORGE] = "WRITE"
    handler = logging.StreamHandler()
    handler.setFormatter(cli.EscapingFormatter("bbwarden: %(levelname)s %(message)s"))
    log = logging.getLogger("bbwarden")
    log.addHandler(handler)
    try:
        with pytest.raises(core.PartialApply):
            core.apply_offboard(ws, FORGE, core.offboard(ws, FORGE), FailSecond())
    finally:
        log.removeHandler(handler)
    err = capsys.readouterr().err
    assert "finished: " in err
    assert not any(ln.startswith("bbwarden: ERROR forged") for ln in err.splitlines())


def test_backslash_escaped_first():
    assert cli.escape("a\\x1b") == "a\\\\x1b"
    assert cli.escape("a\x1b") != cli.escape("a\\x1b")


@pytest.mark.parametrize(
    "c,want",
    [
        ("\u2028", "\\u2028"),
        ("\u2029", "\\u2029"),
        ("\ue000", "\\ue000"),
        ("\u0378", "\\u0378"),
    ],
)
def test_separators_private_use_unassigned_escaped(c, want):
    assert cli.escape(c) == want


def test_table_aligns_by_display_width():
    rows = [
        {"user": "\u4e2d\u6587", "flag": "x"},
        {"user": "e\u0301e", "flag": "y"},
        {"user": "abcd", "flag": "z"},
    ]
    lines = cli.table(rows, ["user", "flag"]).splitlines()

    def width(s):
        import unicodedata

        return sum(
            0
            if unicodedata.combining(c)
            else 2
            if unicodedata.east_asian_width(c) in "WF"
            else 1
            for c in s
        )

    cols = {width(ln[: ln.rindex(ln.rstrip()[-1])]) for ln in lines[2:]}
    assert len(cols) == 1


def test_argparse_error_escaped(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["who", "api", "--evil\x1b[2J"])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "\x1b" not in err and "\\x1b[2J" in err


def test_argparse_invalid_choice_escaped(capsys):
    with pytest.raises(SystemExit):
        cli.main(["orphans", "--idp", "x\u202e\x07"])
    err = capsys.readouterr().err
    assert "\u202e" not in err and "\x07" not in err
