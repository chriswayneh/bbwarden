"""QE round on PR #12 (6f14cb8): --csv to the file stdout already points at."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from bbwarden import cli

ROOT = Path(__file__).resolve().parent.parent
posix = pytest.mark.skipif(os.name == "nt", reason="POSIX redirection")
ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
CLI = [sys.executable, "-m", "bbwarden.cli"]
TIMEOUT = 20


# Same file as stdout: `--csv out.csv > out.csv` and `>> out.csv`


@posix
@pytest.mark.parametrize("append", [False, True])
def test_csv_to_the_file_stdout_is_redirected_to(tmp_path, append):
    out = tmp_path / "out.csv"
    out.write_text("earlier\n", encoding="utf-8")
    ino = os.stat(out).st_ino
    with open(out, "ab" if append else "r+b") as f:
        if append:
            f.seek(0, 2)
        else:
            f.truncate(0)
        r = subprocess.run(
            [*CLI, "direct", "--demo", "--csv", str(out)],
            stdout=f,
            stderr=subprocess.PIPE,
            check=False,
            env=ENV,
            timeout=TIMEOUT,
        )
    assert r.returncode == 0, r.stderr
    text = out.read_text(encoding="utf-8")
    assert os.stat(out).st_ino == ino and sorted(os.listdir(tmp_path)) == ["out.csv"]
    assert ("earlier" in text) == append
    table = text.index("SCOPE")
    assert table < text.index("scope,name,user,permission")
    assert "repo,web,frank,READ" in text


def test_stdout_without_fileno_is_not_treated_as_the_target(tmp_path, monkeypatch):
    class NoFileno:
        def write(self, s):
            return len(s)

        def flush(self):
            pass

        def fileno(self):
            raise OSError("no fileno")

    monkeypatch.setattr(sys, "stdout", NoFileno())
    p = tmp_path / "o.csv"
    cli._check_writable(str(p))
    cli.write_csv([{"user": "x"}], str(p), ["user"])
    assert p.read_text(encoding="utf-8").startswith("user")


RUN_WITH_UMLAUT = """
import sys
from bbwarden import cli
from bbwarden.model import demo_workspace
ws = demo_workspace()
ws.repos["web"]["users"]["j\\u00fcrgen"] = "READ"
cli.get_ws = lambda args, env=None, **kw: (ws, None)
sys.exit(cli.main(sys.argv[1:]))
"""


def _ascii_env():
    return {**ENV, "PYTHONIOENCODING": "ascii:backslashreplace"}


def _csv_part(data):
    i = data.index(b"scope,name,user,permission")
    return data[i:]


def _assert_utf8_crlf(csv_bytes):
    assert b"repo,web,j\xc3\xbcrgen,READ\r\n" in csv_bytes  # exact UTF-8 bytes
    assert b"\r\r\n" not in csv_bytes
    lines = csv_bytes.split(b"\r\n")
    assert lines[-1] == b"" and all(b"\n" not in ln for ln in lines)


@posix
def test_csv_via_stdout_file_is_utf8_crlf_with_ascii_console(tmp_path):
    out = tmp_path / "f.csv"
    with open(out, "wb") as f:
        r = subprocess.run(
            [sys.executable, "-c", RUN_WITH_UMLAUT, "direct", "--csv", str(out)],
            stdout=f,
            stderr=subprocess.PIPE,
            check=False,
            env=_ascii_env(),
            timeout=TIMEOUT,
        )
    assert r.returncode == 0, r.stderr
    data = out.read_bytes()
    assert b"j\\xfcrgen" in data[: data.index(b"scope,name")]  # table: console encoding
    _assert_utf8_crlf(_csv_part(data))


@posix
@pytest.mark.skipif(not os.path.exists("/dev/stdout"), reason="needs /dev/stdout")
def test_csv_to_dev_stdout_pipe_is_utf8_crlf_with_ascii_console():
    r = subprocess.run(
        [sys.executable, "-c", RUN_WITH_UMLAUT, "direct", "--csv", "/dev/stdout"],
        capture_output=True,
        check=False,
        env=_ascii_env(),
        timeout=TIMEOUT,
    )
    assert r.returncode == 0, r.stderr
    _assert_utf8_crlf(_csv_part(r.stdout))


def test_stdout_without_buffer_falls_back_to_text(monkeypatch, tmp_path):
    import io

    class TextOnly(io.StringIO):
        pass

    out = TextOnly()
    monkeypatch.setattr(sys, "stdout", out)
    cli._write_to_stdout([{"user": "j\u00fcrgen"}], ["user"], False)
    assert out.getvalue() == "user\r\nj\u00fcrgen\r\n"


class _PipeBuffer:
    """A byte buffer whose reader went away: write and flush raise EPIPE."""

    closed = False

    def __init__(self, fail_on):
        self.fail_on = fail_on

    def _maybe_fail(self, what):
        if what == self.fail_on:
            import errno

            raise BrokenPipeError(errno.EPIPE, "Broken pipe")

    def write(self, b):
        self._maybe_fail("write")
        return len(b)

    def flush(self):
        self._maybe_fail("flush")

    def close(self):
        self.closed = True

    def writable(self):
        return True

    def readable(self):
        return False

    def seekable(self):
        return False


@pytest.mark.parametrize("fail_on", ["write", "flush"])
def test_broken_pipe_propagates_and_leaves_stdout_buffer_open(monkeypatch, fail_on):
    import gc

    class Out:
        def __init__(self):
            self.buffer = _PipeBuffer(fail_on)

        def write(self, s):
            return len(s)

        def flush(self):
            pass

    out = Out()
    monkeypatch.setattr(sys, "stdout", out)
    with pytest.raises(BrokenPipeError):
        cli._write_to_stdout([{"user": "x"}], ["user"], False)
    gc.collect()  # a dropped wrapper that could not detach closes the buffer here
    assert out.buffer.closed is False
