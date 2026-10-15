"""Terminal escape and bidi injection: table cells and stderr lines never carry raw control
characters; CSV formula guard sees through leading control and format characters."""

import csv
import re
import unicodedata
from pathlib import Path

import pytest
from test_round8 import Backend, run, ws_root

from bbwarden import __version__, cli
from bbwarden.http import ManualStep

ROOT = Path(__file__).parent.parent
EVIL = "evil\x1b]0;pwned\x07\x1b[2J"
BIDI = "\u202eexe.txt"


def raw_controls(s):
    """Characters that must never reach the terminal (newline excluded: it separates lines)."""
    return [
        c
        for c in s
        if c != "\n"
        and (
            ord(c) < 0x20
            or 0x7F <= ord(c) <= 0x9F
            or unicodedata.category(c) in ("Cc", "Cf", "Cs")
        )
    ]


def test_table_poc_no_raw_control_or_bidi():
    out = cli.table([{"user": EVIL, "flag": BIDI}], ["user", "flag"])
    assert raw_controls(out) == []
    assert "\\x1b]0;pwned\\x07\\x1b[2J" in out and "\\u202eexe.txt" in out


def test_table_alignment_uses_escaped_width():
    out = cli.table(
        [{"user": EVIL, "flag": "x"}, {"user": "bob", "flag": "y"}], ["user", "flag"]
    )
    lines = out.splitlines()
    col = lines[0].index("FLAG")
    assert all(ln[col] in "-xy" for ln in lines[1:])


@pytest.mark.parametrize(
    "s,want",
    [
        ("a\x00b", "a\\x00b"),
        ("\x7f", "\\x7f"),
        ("\x9b31m", "\\x9b31m"),
        ("\u200b", "\\u200b"),
        ("\ufeff", "\\ufeff"),
        ("\ud800", "\\ud800"),
        ("\U000e0001", "\\U000e0001"),
        ("tab\there", "tab\\x09here"),
        ("plain ascii, ok", "plain ascii, ok"),
        ("caf\u00e9 \u4e2d", "caf\u00e9 \u4e2d"),
    ],
)
def test_escape_helper(s, want):
    assert cli.escape(s) == want


def test_error_line_escaped(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["who", EVIL, "--demo"])
    msg = str(e.value.code)
    assert raw_controls(msg) == [] and "\\x1b" in msg


def test_manual_and_note_lines_escaped(monkeypatch, capsys):
    ws = ws_root()
    ws.notes.append(f"note {EVIL} {BIDI}")
    run(monkeypatch, Backend(global_exc=ManualStep(f"owner {EVIL}")), ws)
    assert cli.main(["offboard", "root", "--apply"]) == 1
    cap = capsys.readouterr()
    assert "MANUAL" in cap.err and "NOTE:" in cap.err
    assert raw_controls(cap.err) == [] and raw_controls(cap.out) == []


def test_log_lines_escaped(caplog, monkeypatch, capsys):
    import logging

    rec = logging.LogRecord("bbwarden", logging.ERROR, "", 0, "step %s", (EVIL,), None)
    assert raw_controls(cli.EscapingFormatter("%(message)s").format(rec)) == []


@pytest.mark.parametrize(
    "v", ["\u200b=cmd()", "\x1b=cmd()", "\u200e\u200b +1", "\ufeff@SUM(A1)"]
)
def test_csv_formula_after_control_or_format_chars(v, tmp_path):
    p = tmp_path / "o.csv"
    cli.write_csv([{"user": v}], p, ["user"])
    cell = list(csv.reader(p.open()))[1][0]
    assert cell == "'" + v


def test_csv_keeps_data_unescaped(tmp_path):
    p = tmp_path / "o.csv"
    cli.write_csv([{"user": BIDI}], p, ["user"])
    assert list(csv.reader(p.open(encoding="utf-8")))[1][0] == BIDI


def test_requests_floor():
    assert '"requests>=2.32.4"' in (ROOT / "pyproject.toml").read_text()


def test_version_0_2_2_everywhere():
    assert __version__ == "0.2.2"
    assert "bbwarden 0.2.2" in (ROOT / "README.md").read_text()
    assert "## [0.2.2] - 2026-10-15" in (ROOT / "CHANGELOG.md").read_text()
    sec = (ROOT / "SECURITY.md").read_text()
    assert re.search(r"\| 0\.2\.2 \| Yes", sec) and re.search(r"\| 0\.2\.1 \| No", sec)
