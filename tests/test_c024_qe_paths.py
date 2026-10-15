"""QE round on PR #12 (d584660): special --csv targets, Ctrl-C in the global step,
pagination flags and the CSV writer's error paths."""

import errno
import os
from pathlib import Path

import pytest
from fakehttp import Resp

from bbwarden import cli
from bbwarden.http import BBWardenError

ROOT = Path(__file__).resolve().parent.parent
posix = pytest.mark.skipif(os.name == "nt", reason="POSIX special files")
ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src")}


# 4. Pagination: isLastPage must be exactly True


@pytest.mark.parametrize("flag", ["false", "true", 0, 1, None, [], {}])
def test_non_boolean_is_last_page_without_cursor_raises(flag):
    from c024util import h

    s = h({("GET", "/x", None): Resp(body={"values": [1], "isLastPage": flag})})
    with pytest.raises(BBWardenError, match="incomplete pagination"):
        list(s.paginate("x"))


# 4. CSV writer error paths


def test_enospc_in_writerows_keeps_old_file(tmp_path, monkeypatch):
    import csv

    p = tmp_path / "out.csv"
    p.write_text("old", encoding="utf-8")

    def full(self, rows):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(csv.DictWriter, "writerows", full)
    with pytest.raises(OSError) as e:
        cli.write_csv([{"user": "x"}], str(p), ["user"])
    assert e.value.errno == errno.ENOSPC
    assert p.read_text(encoding="utf-8") == "old"
    assert os.listdir(tmp_path) == ["out.csv"]


def test_write_csv_refuses_a_directory(tmp_path):
    with pytest.raises(IsADirectoryError) as e:
        cli.write_csv([], str(tmp_path), ["user"])
    assert e.value.filename == str(tmp_path) and os.listdir(tmp_path) == []


def test_remove_quietly_ignores_oserror(tmp_path):
    cli._remove_quietly(str(tmp_path / "missing"))  # no exception
    d = tmp_path / "dir"
    d.mkdir()
    cli._remove_quietly(str(d))  # IsADirectoryError / PermissionError is an OSError
    assert d.is_dir()


def test_temp_name_collision_retries(tmp_path, monkeypatch):
    names = iter(["aaaa", "aaaa", "bbbb"])
    monkeypatch.setattr(cli.secrets, "token_hex", lambda n: next(names))
    fd1, t1 = cli._temp_sibling(str(tmp_path / "o.csv"), "o.csv", 0o600)
    fd2, t2 = cli._temp_sibling(str(tmp_path / "o.csv"), "o.csv", 0o600)
    os.close(fd1)
    os.close(fd2)
    assert os.path.basename(t1) == ".bbwarden-aaaa.tmp"
    assert os.path.basename(t2) == ".bbwarden-bbbb.tmp"


def test_temp_name_exhaustion_names_the_target(tmp_path, monkeypatch):
    (tmp_path / ".bbwarden-same.tmp").write_text("", encoding="utf-8")
    calls = []

    def same(n):
        calls.append(n)
        return "same"

    monkeypatch.setattr(cli.secrets, "token_hex", same)
    with pytest.raises(FileExistsError) as e:
        cli._temp_sibling(str(tmp_path / "o.csv"), "shown.csv", 0o600)
    assert e.value.filename == "shown.csv" and len(calls) == 100
