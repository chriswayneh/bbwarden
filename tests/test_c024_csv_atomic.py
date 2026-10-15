"""Codex runner-2026-10-15 on dfd0b68: 8. CSV path check never deletes someone else's file; writes are atomic."""

import csv
import os

import pytest

from bbwarden import cli

# 8. CSV path check never deletes someone else's file; writes are atomic


def test_f8_check_writable_never_removes_existing_file(tmp_path, monkeypatch):
    p = tmp_path / "out.csv"
    p.write_text("keep me", encoding="utf-8")
    monkeypatch.setattr(
        cli.os.path, "exists", lambda path: False
    )  # race: appeared late
    cli._check_writable(str(p))
    assert p.read_text(encoding="utf-8") == "keep me"


def test_f8_failed_write_keeps_old_file(tmp_path, monkeypatch):
    p = tmp_path / "out.csv"
    p.write_text("old", encoding="utf-8")

    def boom(self, rows):
        raise OSError("disk full")

    monkeypatch.setattr(csv.DictWriter, "writerows", boom)
    with pytest.raises(OSError):
        cli.write_csv([{"user": "x"}], str(p), ["user"])
    assert p.read_text(encoding="utf-8") == "old"
    assert sorted(os.listdir(tmp_path)) == ["out.csv"]
