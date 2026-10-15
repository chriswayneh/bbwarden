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


@posix
@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs mkfifo")
def test_csv_to_fifo_writes_into_the_pipe(tmp_path):
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    got = []
    reader = threading.Thread(target=lambda: got.append(fifo.read_bytes()), daemon=True)
    reader.start()
    try:
        code = cli.main(["direct", "--demo", "--csv", str(fifo)])
    finally:
        reader.join(5)
    assert code == 0
    assert got and got[0].startswith(b"scope,name,user")
    assert fifo.is_fifo() and sorted(os.listdir(tmp_path)) == ["pipe"]


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
