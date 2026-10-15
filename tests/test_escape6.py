"""Review of 321e62c: tracebacks show exception types only (no secrets), Ctrl-C handling,
default-mode CSV coverage for the formula cases."""

import csv
import logging
import sys

import pytest

from bbwarden import cli, core
from bbwarden.http import BBWardenError

SECRET_MSG = "token=SECRET123 https://u:p@h/x"


def assert_no_secret(text):
    assert "SECRET123" not in text and "u:p" not in text


def test_last_resort_hides_message(monkeypatch, capsys):
    def boom(*a, **k):
        raise ValueError(SECRET_MSG)

    monkeypatch.setattr(core, "who", boom)
    with pytest.raises(SystemExit) as e:
        cli.main(["who", "api", "--demo"])
    assert e.value.code == 1
    err = capsys.readouterr().err
    assert_no_secret(err)
    assert "Traceback (most recent call last):" in err and '  File "' in err
    assert err.rstrip().splitlines()[-1] == "ValueError"


def test_last_resort_hides_chain_and_notes(monkeypatch, capsys):
    def boom(*a, **k):
        try:
            raise KeyError(SECRET_MSG)
        except KeyError as inner:
            e = RuntimeError(SECRET_MSG)
            if hasattr(e, "add_note"):
                e.add_note(SECRET_MSG)
            raise e from inner

    monkeypatch.setattr(core, "who", boom)
    with pytest.raises(SystemExit):
        cli.main(["who", "api", "--demo"])
    err = capsys.readouterr().err
    assert_no_secret(err)
    assert "\nKeyError\n" in err and err.rstrip().endswith("RuntimeError")


@pytest.mark.skipif(sys.version_info < (3, 11), reason="ExceptionGroup needs 3.11")
def test_group_members_hidden():
    eg = (
        __builtins__["ExceptionGroup"]
        if isinstance(__builtins__, dict)
        else __builtins__.ExceptionGroup
    )
    exc = eg(
        SECRET_MSG,
        [ValueError(SECRET_MSG), BBWardenError("HTTP 500 on GET https://h/x")],
    )
    out = "\n".join(cli._exc_lines(exc, safe=True))
    assert_no_secret(out)
    assert "| ValueError" in out and "HTTP 500 on GET https://h/x" in out


def test_formatter_tracebacks_type_only_by_default():
    try:
        raise ValueError(SECRET_MSG)
    except ValueError:
        ei = sys.exc_info()
    rec = logging.LogRecord("bbwarden", logging.ERROR, "", 0, "boom", None, ei)
    out = cli.EscapingFormatter("%(message)s").format(rec)
    assert_no_secret(out)
    assert out.splitlines()[-1] == "ValueError"


def test_bbwarden_error_message_kept_in_traceback():
    out = cli._exc_lines(
        BBWardenError("HTTP 401 on GET https://bb.example.com/x"), safe=True
    )
    assert out[-1].endswith("BBWardenError: HTTP 401 on GET https://bb.example.com/x")


def test_keyboard_interrupt_exit_130(monkeypatch, capsys):
    def stop(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_run", stop)
    with pytest.raises(SystemExit) as e:
        cli.main(["direct", "--demo"])
    assert e.value.code == 130
    err = capsys.readouterr().err
    assert err.strip() == "interrupted" and "Traceback" not in err


@pytest.mark.parametrize(
    "v", ["\u200b=cmd()", "\x1b=cmd()", "\u200e\u200b +1", "\ufeff@SUM(A1)", "=1+1"]
)
def test_default_csv_formula_cases(v, tmp_path):
    p = tmp_path / "o.csv"
    cli.write_csv([{"user": v}], p, ["user"])
    with open(p, encoding="utf-8", newline="") as f:
        cell = list(csv.reader(f))[1][0]
    assert cell == cli._safe_cell(v)
    assert not cell.startswith(("=", "+", "-", "@", "\t", "\r"))
    assert not any(cli._is_control(c) for c in cell)
