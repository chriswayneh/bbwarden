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


# A broken stdout must never hide exit 1 or 3 (reviewer, 3e9a49e)

RUNNER = """
import sys
from bbwarden import cli
from bbwarden.http import ManualStep
from bbwarden.model import demo_workspace

class Backend:
    def load_memberships(self, ws, user): pass
    def remove_user(self, ws, scope, key, user): pass
    def remove_member(self, group, user): pass
    def remove_global(self, user): raise ManualStep("owners cannot be removed by API")

ws = demo_workspace()
mode = sys.argv.pop(1)
if mode == "manual":
    ws.admins["dave"] = "workspace:owner"
else:
    ws.notes.append("global admin users not loaded (HTTP 403)")
cli.get_ws = lambda args, env=None, **kw: (ws, Backend())
sys.exit(cli.main(sys.argv[1:]))
"""


@posix
@pytest.mark.parametrize("csv", [[], ["--csv", "/dev/stdout"]], ids=["table", "csv"])
def test_closed_reader_apply_with_manual_step_exits_1(csv):
    r = _closed_reader(
        [sys.executable, "-c", RUNNER, "manual", "offboard", "dave", "--apply", *csv]
    )
    assert r.returncode == 1, r.stderr
    assert b"MANUAL" in r.stderr and b"APPLY INCOMPLETE" in r.stderr
    assert b"Traceback" not in r.stderr and b"Exception ignored" not in r.stderr


@posix
@pytest.mark.parametrize("csv", [[], ["--csv", "/dev/stdout"]], ids=["table", "csv"])
def test_closed_reader_incomplete_inventory_exits_3(csv):
    r = _closed_reader([sys.executable, "-c", RUNNER, "notes", "direct", *csv])
    assert r.returncode == 3, r.stderr
    assert b"NOTE:" in r.stderr and b"INCOMPLETE:" in r.stderr
    assert b"Traceback" not in r.stderr and b"Exception ignored" not in r.stderr


class _BreaksOnFlush:
    def write(self, s):
        return len(s)

    def flush(self):
        raise BrokenPipeError(32, "Broken pipe")

    def fileno(self):
        raise OSError("no fileno")


@pytest.mark.parametrize("rc,want", [(0, 141), (1, 1), (2, 2), (3, 3)])
def test_break_at_final_flush_keeps_a_stronger_code(monkeypatch, rc, want):
    from bbwarden import cli

    monkeypatch.setattr(cli, "_run", lambda args, env, **kw: rc)
    monkeypatch.setattr(sys, "stdout", _BreaksOnFlush())
    try:
        got = cli.main(["direct", "--demo"])
    except SystemExit as e:
        got = e.code
    assert got == want


@pytest.mark.parametrize("rc,want", [(0, 141), (1, 1), (3, 3)])
def test_entry_break_at_final_flush_keeps_a_stronger_code(monkeypatch, rc, want):
    from bbwarden import _entry, cli

    monkeypatch.setattr(cli, "main", lambda: rc)
    monkeypatch.setattr(sys, "stdout", _BreaksOnFlush())
    with pytest.raises(SystemExit) as e:
        _entry.run()
    assert e.value.code == want
