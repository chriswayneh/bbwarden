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
