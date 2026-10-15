"""QE round on PR #12 (d584660): special --csv targets, Ctrl-C in the global step,
pagination flags and the CSV writer's error paths."""

import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from bbwarden import cli

ROOT = Path(__file__).resolve().parent.parent
posix = pytest.mark.skipif(os.name == "nt", reason="POSIX special files")
ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src")}


# 1. --csv to a FIFO, /dev/stdout or /dev/fd/N writes directly, no temp or rename


CLI = [sys.executable, "-m", "bbwarden.cli"]
TIMEOUT = 20  # a mutant that opens or blocks on a FIFO fails here instead of hanging
fifo_ok = pytest.mark.skipif(
    os.name == "nt" or not hasattr(os, "mkfifo"), reason="needs mkfifo"
)


def _read_fifo(fifo, got):
    t = threading.Thread(target=lambda: got.append(fifo.read_bytes()), daemon=True)
    t.start()
    return t


@fifo_ok
def test_csv_to_fifo_writes_into_the_pipe(tmp_path):
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    got: list = []
    reader = _read_fifo(fifo, got)
    r = subprocess.run(
        [*CLI, "direct", "--demo", "--csv", str(fifo)],
        capture_output=True,
        check=False,
        env=ENV,
        timeout=TIMEOUT,
    )
    reader.join(TIMEOUT)
    assert not reader.is_alive()
    assert r.returncode == 0, r.stderr
    assert got and got[0].startswith(b"scope,name,user")
    assert fifo.is_fifo() and sorted(os.listdir(tmp_path)) == ["pipe"]


@fifo_ok
def test_check_writable_never_opens_a_fifo(tmp_path):
    """With no reader, opening a FIFO blocks forever. The check must not open it; a
    mutant that does is killed by the timeout instead of hanging the suite."""
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    code = f"from bbwarden import cli; cli._check_writable({str(fifo)!r})"
    try:
        r = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            check=False,
            env=ENV,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("_check_writable blocked on the FIFO")
    assert r.returncode == 0, r.stderr
    assert sorted(os.listdir(tmp_path)) == ["pipe"]


@fifo_ok
def test_read_only_fifo_refused_before_output(tmp_path):
    fifo = tmp_path / "ro"
    os.mkfifo(fifo, 0o444)
    if os.access(fifo, os.W_OK):
        pytest.skip("running as root: permission bits are not enforced")
    r = subprocess.run(
        [*CLI, "direct", "--demo", "--csv", str(fifo)],
        capture_output=True,
        check=False,
        env=ENV,
        timeout=TIMEOUT,
    )
    assert r.returncode == 1
    assert r.stdout == b"" and b"Permission denied" in r.stderr


@fifo_ok
def test_stdout_flushed_before_special_target_is_written(tmp_path, monkeypatch):
    """The table (buffered on stdout) must be flushed before the CSV goes to a special
    target, so /dev/tty-like targets show the table first."""
    events = []

    class Out:
        def write(self, s):
            events.append("table")
            return len(s)

        def flush(self):
            events.append("flush")

    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    got: list = []
    reader = _read_fifo(fifo, got)
    real_open = open

    def spy_open(path, *a, **k):
        if str(path) == str(fifo):
            events.append("csv")
        return real_open(path, *a, **k)

    monkeypatch.setattr(sys, "stdout", Out())
    monkeypatch.setattr("builtins.open", spy_open)
    cli.write_csv([{"user": "x"}], str(fifo), ["user"])
    reader.join(TIMEOUT)
    assert events.index("flush") < events.index("csv")
    assert got and got[0].startswith(b"user")


@posix
@pytest.mark.skipif(not os.path.exists("/dev/stdout"), reason="needs /dev/stdout")
def test_csv_to_dev_stdout_subprocess():
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "bbwarden.cli",
            "direct",
            "--demo",
            "--csv",
            "/dev/stdout",
        ],
        capture_output=True,
        check=False,
        env=ENV,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    assert b"scope,name,user,permission" in r.stdout


@posix
@pytest.mark.skipif(not os.path.isdir("/dev/fd"), reason="needs /dev/fd")
def test_csv_to_dev_fd_like_process_substitution():
    rfd, wfd = os.pipe()
    try:
        p = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "bbwarden.cli",
                "direct",
                "--demo",
                "--csv",
                f"/dev/fd/{wfd}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            pass_fds=(wfd,),
            env=ENV,
        )
        os.close(wfd)
        wfd = -1
        with os.fdopen(rfd, "rb") as r:
            rfd = -1
            data = r.read()
        assert p.wait(60) == 0, p.stderr.read()
        p.stderr.close()
    finally:
        for fd in (rfd, wfd):
            if fd >= 0:
                os.close(fd)
    assert data.startswith(b"scope,name,user,permission")


@posix
@pytest.mark.skipif(
    not hasattr(__import__("socket"), "AF_UNIX"), reason="needs AF_UNIX"
)
def test_csv_to_unix_socket_is_refused_before_output(capsys):
    import shutil
    import socket
    import tempfile

    d = tempfile.mkdtemp(prefix="bbw")  # short path: AF_UNIX names are length-limited
    try:
        path = os.path.join(d, "s")
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(path)
        try:
            with pytest.raises(SystemExit) as e:
                cli.main(["direct", "--demo", "--csv", path])
        finally:
            s.close()
        assert e.value.code == 2
        cap = capsys.readouterr()
        assert cap.out == "" and "socket" in cap.err
        assert os.path.exists(path)
    finally:
        shutil.rmtree(d)
