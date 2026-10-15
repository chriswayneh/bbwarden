"""Review minors on codex-fixes-0.2.4: symlink targets, file modes, fd hygiene."""

import os
import stat

import pytest

from bbwarden import cli

needs_symlink = pytest.mark.skipif(
    not hasattr(os, "symlink") or os.name == "nt", reason="needs symlinks"
)


@needs_symlink
def test_csv_to_symlink_updates_target_and_keeps_link(tmp_path):
    target = tmp_path / "real.csv"
    target.write_text("old", encoding="utf-8")
    link = tmp_path / "link.csv"
    os.symlink(target, link)
    assert cli.main(["direct", "--demo", "--csv", str(link)]) == 0
    assert os.path.islink(link) and os.readlink(link) == str(target)
    assert target.read_text(encoding="utf-8").startswith("scope,name,user")
    assert sorted(os.listdir(tmp_path)) == ["link.csv", "real.csv"]


@needs_symlink
def test_check_writable_follows_symlink(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    os.symlink(d / "real.csv", tmp_path / "link.csv")
    cli._check_writable(str(tmp_path / "link.csv"))  # probes d, not tmp_path
    assert sorted(os.listdir(d)) == []


def test_new_csv_gets_umask_mode_without_changing_umask(tmp_path, monkeypatch):
    mask = os.umask(0o22)
    os.umask(mask)

    def no_umask(*a):
        raise AssertionError("os.umask must not be called")

    monkeypatch.setattr(cli.os, "umask", no_umask)
    p = tmp_path / "new.csv"
    cli.write_csv([], str(p), ["user"])
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o666 & ~mask


def test_existing_csv_keeps_mode(tmp_path):
    p = tmp_path / "old.csv"
    p.write_text("x", encoding="utf-8")
    os.chmod(p, 0o640)
    cli.write_csv([], str(p), ["user"])
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o640


def test_fd_closed_and_temp_removed_if_fdopen_fails(tmp_path, monkeypatch):
    opened = []
    real_open = os.open

    def track(*a, **k):
        fd = real_open(*a, **k)
        opened.append(fd)
        return fd

    def boom(*a, **k):
        raise MemoryError

    monkeypatch.setattr(cli.os, "open", track)
    monkeypatch.setattr(cli.os, "fdopen", boom)
    with pytest.raises(MemoryError):
        cli.write_csv([], str(tmp_path / "o.csv"), ["user"])
    assert opened
    for fd in opened:
        with pytest.raises(OSError):
            os.fstat(fd)
    assert os.listdir(tmp_path) == []


def _umask():
    mask = os.umask(0o22)
    os.umask(mask)
    return mask


def _watch_temp_modes(monkeypatch):
    """Record the temp file's mode at the moment rows are written."""
    import csv

    seen = []
    real = csv.DictWriter.writerows

    def spy(self, rows):
        seen.append(stat.S_IMODE(os.fstat(self.writer_fd).st_mode))
        return real(self, rows)

    real_fdopen = os.fdopen

    def fdopen(fd, *a, **k):
        f = real_fdopen(fd, *a, **k)
        csv.DictWriter.writer_fd = fd
        return f

    monkeypatch.setattr(cli.os, "fdopen", fdopen)
    monkeypatch.setattr(csv.DictWriter, "writerows", spy)
    return seen


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_temp_csv_is_0600_while_written_new_file(tmp_path, monkeypatch):
    mask = _umask()
    seen = _watch_temp_modes(monkeypatch)
    monkeypatch.setattr(cli.os, "umask", lambda *a: pytest.fail("umask called"))
    p = tmp_path / "new.csv"
    cli.write_csv([{"user": "x"}], str(p), ["user"])
    assert seen == [0o600]
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o666 & ~mask


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_temp_csv_is_0600_while_rewriting_private_report(tmp_path, monkeypatch):
    p = tmp_path / "old.csv"
    p.write_text("x", encoding="utf-8")
    os.chmod(p, 0o600)
    seen = _watch_temp_modes(monkeypatch)
    monkeypatch.setattr(cli.os, "umask", lambda *a: pytest.fail("umask called"))
    cli.write_csv([{"user": "x"}], str(p), ["user"])
    assert seen == [0o600]
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
