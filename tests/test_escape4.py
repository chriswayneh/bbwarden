"""Review of 652caa7: the traceback renderer must never raise, whatever the exception."""

import builtins
import logging
import sys

from test_escape3 import needs_311

from bbwarden import cli

FORGE = "\nbbwarden: ERROR forged"


def log_to_stderr(exc_info):
    handler = logging.StreamHandler()
    handler.setFormatter(cli.EscapingFormatter("bbwarden: %(levelname)s %(message)s"))
    log = logging.getLogger("bbwarden.test_escape4")
    log.addHandler(handler)
    try:
        log.error("boom", exc_info=exc_info)
    finally:
        log.removeHandler(handler)


def check(err, max_lines=2000):
    assert "--- Logging error ---" not in err
    lines = err.splitlines()
    assert lines[0] == "bbwarden: ERROR boom"
    assert not any(ln.startswith("bbwarden: ERROR forged") for ln in lines)
    assert "\x1b" not in err and len(lines) < max_lines


def test_long_chain_does_not_raise_and_is_bounded(capsys):
    exc = ValueError(f"0{FORGE}")
    for i in range(1, 5000):
        nxt = ValueError(f"{i}{FORGE}\x1b[2J")
        nxt.__cause__ = exc
        exc = nxt
    log_to_stderr((ValueError, exc, None))
    err = capsys.readouterr().err
    check(err)
    assert "more chained exceptions" in err and "ValueError: 4999\\x0a" in err


@needs_311
def test_deep_group_does_not_raise_and_is_bounded(capsys):
    eg = builtins.ExceptionGroup
    exc = ValueError(f"leaf{FORGE}")
    for _ in range(3000):
        exc = eg(f"g{FORGE}", [exc])
    log_to_stderr((type(exc), exc, None))
    err = capsys.readouterr().err
    check(err)
    assert "nested too deep" in err


@needs_311
def test_bad_note_does_not_raise(capsys):
    class BadNote:
        def __str__(self):
            raise RuntimeError("no")

    e = ValueError(f"m{FORGE}")
    e.__notes__ = [BadNote(), "ok"]
    log_to_stderr((ValueError, e, None))
    err = capsys.readouterr().err
    check(err)
    assert (
        "ValueError: m\\x0abbwarden: ERROR forged\\x0a<note str() failed>\\x0aok" in err
    )


def test_renderer_failure_falls_back(monkeypatch, capsys):
    def explode(_exc):
        raise RecursionError("deep")

    monkeypatch.setattr(cli, "_exc_lines", explode)
    log_to_stderr((ValueError, ValueError(f"x{FORGE}"), None))
    err = capsys.readouterr().err
    check(err)
    assert "ValueError: <traceback unavailable>" in err


def test_exc_info_without_instance_does_not_instantiate(capsys):
    class NeedsArgs(Exception):
        def __init__(self, a, b):
            super().__init__(a, b)

    log_to_stderr((NeedsArgs, None, None))
    err = capsys.readouterr().err
    check(err)
    assert err.splitlines()[-1] == "NeedsArgs"


def test_recursion_limit_safe(capsys):
    """Chain longer than the interpreter recursion limit."""
    n = sys.getrecursionlimit() * 3
    exc = KeyError("start")
    for _ in range(n):
        nxt = KeyError("k")
        nxt.__context__ = exc
        exc = nxt
    log_to_stderr((KeyError, exc, None))
    check(capsys.readouterr().err)


def test_cap_is_documented():
    assert 10 <= getattr(cli, "MAX_EXC_DEPTH", 0) <= 100


@needs_311
def test_wide_group_members_capped(capsys):
    eg = builtins.ExceptionGroup
    exc = eg(f"wide{FORGE}", [ValueError(f"m{i}{FORGE}") for i in range(5000)])
    log_to_stderr((type(exc), exc, None))
    err = capsys.readouterr().err
    check(err, max_lines=500)
    assert "sub-exception 50 of 5000" in err and "sub-exception 51 of" not in err
    assert "... (4950 more sub-exceptions)" in err
