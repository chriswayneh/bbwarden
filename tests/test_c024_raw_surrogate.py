"""Codex runner-2026-10-15 on dfd0b68: Known limit: raw CSV surrogate."""

import csv

from bbwarden import cli

# Known limit 1: raw CSV surrogate vs literal text


def test_l1_raw_csv_surrogate_distinguishable(tmp_path):
    p = tmp_path / "o.csv"
    cli.write_csv(
        [{"user": "bad\ud800"}, {"user": "bad\\ud800"}], str(p), ["user"], raw=True
    )
    with open(p, encoding="utf-8", newline="") as f:
        rows = [r[0] for r in csv.reader(f)][1:]
    assert rows == ["bad\ufffd", "bad\\ud800"]
