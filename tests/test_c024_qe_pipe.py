"""QE round 3 on PR #12 (00c8ca3): broken stdout pipe exits 141 quietly."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
posix = pytest.mark.skipif(os.name == "nt", reason="POSIX pipes and modes")
ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
TIMEOUT = 20
ENTRY = "import sys; from bbwarden._entry import run; sys.argv[0] = 'bbwarden'; run()"


def _closed_reader(argv):
    rfd, wfd = os.pipe()
    os.close(rfd)  # the reader is gone before bbwarden writes anything
    try:
        return subprocess.run(
            argv,
            stdout=wfd,
            stderr=subprocess.PIPE,
            check=False,
            env=ENV,
            timeout=TIMEOUT,
        )
    finally:
        os.close(wfd)


@posix
@pytest.mark.parametrize("entry", ["cli", "console-script"])
@pytest.mark.parametrize("csv", [[], ["--csv", "/dev/stdout"]], ids=["table", "csv"])
def test_broken_stdout_pipe_exits_141_quietly(entry, csv):
    head = (
        [sys.executable, "-m", "bbwarden.cli"]
        if entry == "cli"
        else [sys.executable, "-c", ENTRY]
    )
    r = _closed_reader([*head, "direct", "--demo", *csv])
    assert r.returncode == 141, r.stderr
    assert b"Exception ignored" not in r.stderr and b"Traceback" not in r.stderr
