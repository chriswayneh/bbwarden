"""QE round 4 on PR #12 (db30873): closed stdout, argparse output to a closed reader,
an unwritable stdout (/dev/full), and no exit 120 anywhere."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
posix = pytest.mark.skipif(os.name == "nt", reason="POSIX shells and devices")
ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
TIMEOUT = 20
CLI = [sys.executable, "-m", "bbwarden.cli"]
ENTRY = [
    sys.executable,
    "-c",
    "import sys; from bbwarden._entry import run; sys.argv[0] = 'bbwarden'; run()",
]
HEADS = pytest.mark.parametrize("head", [CLI, ENTRY], ids=["cli", "console-script"])
full = pytest.mark.skipif(not os.path.exists("/dev/full"), reason="needs /dev/full")


def _quiet(r):
    assert b"Exception ignored" not in r.stderr and b"Traceback" not in r.stderr
    assert r.returncode != 120


def _sh(cmd, cwd):
    """Run through /bin/sh so `>&-` and `> /dev/full` are real shell redirections."""
    return subprocess.run(
        ["/bin/sh", "-c", cmd],
        capture_output=True,
        check=False,
        env=ENV,
        cwd=cwd,
        timeout=TIMEOUT,
    )


def _q(argv):
    import shlex

    return " ".join(shlex.quote(a) for a in argv)


def _closed_reader(argv):
    rfd, wfd = os.pipe()
    os.close(rfd)
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


# 1. stdout closed (`>&-`): sys.stdout is None


@posix
@HEADS
def test_closed_stdout_still_writes_csv(tmp_path, head):
    r = _sh(_q([*head, "direct", "--demo", "--csv", "c1.csv"]) + " >&-", tmp_path)
    _quiet(r)
    assert r.returncode == 0, r.stderr
    assert (
        (tmp_path / "c1.csv").read_bytes().startswith(b"scope,name,user,permission\r\n")
    )


@posix
@HEADS
def test_closed_stdout_with_version(tmp_path, head):
    r = _sh(_q([*head, "--version"]) + " >&-", tmp_path)
    _quiet(r)
    assert r.returncode == 0, r.stderr


# 2. argparse output (--help, --version, direct --help) to a closed reader


@posix
@HEADS
@pytest.mark.parametrize(
    "args",
    [["--help"], ["--version"], ["direct", "--help"]],
    ids=["help", "version", "sub-help"],
)
def test_argparse_output_to_closed_reader_exits_141(head, args):
    r = _closed_reader([*head, *args])
    _quiet(r)
    assert r.returncode == 141, r.stderr


@posix
@HEADS
def test_argparse_usage_error_keeps_2_with_closed_reader(head):
    r = _closed_reader([*head, "nosuchcommand"])
    _quiet(r)
    assert r.returncode == 2


# 3. stdout fails with a non-pipe error (/dev/full)


@posix
@full
@HEADS
@pytest.mark.parametrize(
    "args",
    [["direct", "--demo"], ["--version"], ["--help"]],
    ids=["direct", "version", "help"],
)
def test_unwritable_stdout_exits_1_with_error(tmp_path, head, args):
    r = _sh(_q([*head, *args]) + " > /dev/full", tmp_path)
    _quiet(r)
    assert r.returncode == 1, r.stderr
    assert b"error: cannot write to stdout" in r.stderr


@posix
@full
@HEADS
def test_unwritable_stdout_keeps_config_error_2(tmp_path, head):
    env = {k: v for k, v in ENV.items() if not k.startswith("BBWARDEN_")}
    r = subprocess.run(
        ["/bin/sh", "-c", _q([*head, "direct"]) + " > /dev/full"],
        capture_output=True,
        check=False,
        env=env,
        cwd=tmp_path,
        timeout=TIMEOUT,
    )
    _quiet(r)
    assert r.returncode == 2, r.stderr


@posix
@full
@HEADS
def test_unwritable_stdout_with_csv_to_stdout(tmp_path, head):
    r = _sh(
        _q([*head, "direct", "--demo", "--csv", "/dev/stdout"]) + " > /dev/full",
        tmp_path,
    )
    _quiet(r)
    assert r.returncode == 1, r.stderr
    assert r.stderr.count(b"error: cannot write to stdout") == 1


# Other ways to 120: an error exit or Ctrl-C while stdout is already unflushable


@posix
@full
@HEADS
def test_error_exit_with_unwritable_stdout_is_not_120(tmp_path, head):
    r = _sh(_q([*head, "who", "nosuchrepo", "--demo"]) + " > /dev/full", tmp_path)
    _quiet(r)
    assert r.returncode == 1, r.stderr


@posix
def test_ctrl_c_with_pending_output_to_closed_reader_is_130():
    code = """
import sys
from bbwarden import cli
def stop(*a, **k):
    print("pending table output")
    raise KeyboardInterrupt
cli._run = stop
sys.exit(cli.main(["direct", "--demo"]))
"""
    r = _closed_reader([sys.executable, "-c", code])
    _quiet(r)
    assert r.returncode == 130 and b"interrupted" in r.stderr


def test_helper_skips_none_stdout(monkeypatch):
    from bbwarden import cli

    monkeypatch.setattr(sys, "stdout", None)
    assert cli.stdout_call(lambda out: out.flush()) == "ok"
    out = cli._Stdout()
    out.print("x")
    assert out.state == "ok"
    cli._write_to_stdout([{"user": "x"}], ["user"], False)
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0


# Reviewer minors at ee97a1a: an unwritable stderr keeps the real exit code


def _noenv():
    return {k: v for k, v in ENV.items() if not k.startswith(("BBWARDEN_", "CROWD_"))}


@posix
@full
@HEADS
@pytest.mark.parametrize(
    "args,redir,want",
    [
        (["nosuchcommand"], "2>/dev/full", 2),
        (["direct"], "2>/dev/full", 2),
        (["nosuchcommand"], ">/dev/full 2>/dev/full", 2),
        (["direct"], ">/dev/full 2>/dev/full", 2),
        (["who", "nosuchrepo", "--demo"], "2>/dev/full", 1),
        (["direct", "--demo"], ">/dev/full 2>/dev/full", 1),
        (["direct", "--demo"], "2>/dev/full", 0),
    ],
)
def test_unwritable_stderr_keeps_exit_code(tmp_path, head, args, redir, want):
    r = subprocess.run(
        ["/bin/sh", "-c", f"{_q([*head, *args])} {redir}"],
        stdout=subprocess.DEVNULL,
        check=False,
        env=_noenv(),
        cwd=tmp_path,
        timeout=TIMEOUT,
    )
    assert r.returncode == want
