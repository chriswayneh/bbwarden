"""Review of 48cdc94: exception notes, ExceptionGroup and chained exceptions in log
tracebacks can never forge a log line."""

import builtins
import logging
import sys

import pytest

from bbwarden import cli

FORGE = "\nbbwarden: ERROR forged"
needs_311 = pytest.mark.skipif(
    sys.version_info < (3, 11), reason="notes and ExceptionGroup need 3.11"
)


def render(exc):
    f = cli.EscapingFormatter("bbwarden: %(levelname)s %(message)s", safe=False)
    rec = logging.LogRecord(
        "bbwarden",
        logging.ERROR,
        "",
        0,
        "boom",
        None,
        (type(exc), exc, exc.__traceback__),
    )
    return f.format(rec)


def raised(make):
    try:
        make()
    except BaseException as e:  # noqa: BLE001 - capture any test exception
        return e
    raise AssertionError("did not raise")


def no_forgery(out):
    lines = out.splitlines()
    assert not any(ln.startswith("bbwarden: ERROR forged") for ln in lines), out
    assert lines[0] == "bbwarden: ERROR boom"
    assert "\x1b" not in out and "\r" not in out


@needs_311
def test_note_cannot_forge():
    def make():
        e = ValueError("msg")
        e.add_note(f"a{FORGE}")
        e.add_note("second note")
        raise e

    out = render(raised(make))
    no_forgery(out)
    assert "ValueError: msg\\x0aa\\x0abbwarden: ERROR forged\\x0asecond note" in out
    assert "Traceback (most recent call last):" in out


@needs_311
def test_exception_group_cannot_forge_and_is_readable():
    def make():
        inner = KeyError("k")
        raise builtins.ExceptionGroup(
            f"group{FORGE}", [ValueError(f"v{FORGE}\x1b[2J"), inner]
        )

    out = render(raised(make))
    no_forgery(out)
    assert "ExceptionGroup: group\\x0abbwarden: ERROR forged (2 sub-exceptions)" in out
    assert "sub-exception 1 of 2" in out and "sub-exception 2 of 2" in out
    assert "ValueError: v\\x0abbwarden: ERROR forged\\x1b[2J" in out
    assert "KeyError: 'k'" in out


def test_chained_cause_and_context_cannot_forge():
    def make():
        try:
            try:
                raise ValueError(f"inner{FORGE}")
            except ValueError:
                raise TypeError(f"middle{FORGE}")
        except TypeError as e:
            raise RuntimeError(f"outer{FORGE}") from e

    out = render(raised(make))
    no_forgery(out)
    assert "During handling of the above exception, another exception occurred:" in out
    assert "The above exception was the direct cause of the following exception:" in out
    for t in ("ValueError: inner", "TypeError: middle", "RuntimeError: outer"):
        assert f"{t}\\x0abbwarden: ERROR forged" in out
    assert out.index("ValueError") < out.index("TypeError") < out.index("RuntimeError")


def test_frames_keep_real_lines():
    out = render(raised(lambda: 1 / 0))
    lines = out.splitlines()
    assert lines[1] == "Traceback (most recent call last):"
    assert any(ln.startswith('  File "') for ln in lines)
    assert lines[-1] == "ZeroDivisionError: division by zero"


def test_message_without_text_and_bad_str():
    class Bad(Exception):
        def __str__(self):
            raise RuntimeError("no")

    assert (
        render(raised(lambda: (_ for _ in ()).throw(KeyError()))).splitlines()[-1]
        == "KeyError"
    )
    out = render(raised(lambda: (_ for _ in ()).throw(Bad())))
    assert out.splitlines()[-1].endswith("Bad: <exception str() failed>")
