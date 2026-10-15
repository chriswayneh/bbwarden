"""QE round 3 on PR #12 (00c8ca3): `>>` to stdout's file in a read-only folder."""

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
posix = pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
TIMEOUT = 20


@posix
def test_append_to_stdout_file_in_read_only_folder(tmp_path):
    d = tmp_path / "ro"
    d.mkdir()
    out = d / "o.txt"
    out.write_text("earlier\n", encoding="utf-8")
    d.chmod(0o555)
    try:
        if os.access(d, os.W_OK):
            pytest.skip("running as root: folder modes are not enforced")
        with open(out, "ab") as f:
            r = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "bbwarden.cli",
                    "direct",
                    "--demo",
                    "--csv",
                    str(out),
                ],
                stdout=f,
                stderr=subprocess.PIPE,
                check=False,
                env=ENV,
                timeout=TIMEOUT,
            )
        assert r.returncode == 0, r.stderr
        text = out.read_bytes().decode("utf-8")
        assert text.startswith("earlier\n")
        assert text.index("SCOPE") < text.index("scope,name,user,permission")
        assert text.endswith("repo,web,frank,READ\r\n")
        assert sorted(os.listdir(d)) == ["o.txt"]
    finally:
        d.chmod(stat.S_IRWXU)
