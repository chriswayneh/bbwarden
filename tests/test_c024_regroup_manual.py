"""Codex runner-2026-10-15 on dfd0b68: 5. manual regroup rows are not "applied"."""

from bbwarden import cli

# 5. manual regroup rows are not "applied"


def test_f5_regroup_apply_with_manual_rows_exit_1(capsys):
    assert cli.main(["regroup", "api", "--demo", "--apply"]) == 1
    cap = capsys.readouterr()
    assert "MANUAL" in cap.err and "erin" in cap.err
    assert "APPLIED" not in cap.out


def test_f5_regroup_dry_run_with_manual_rows_exit_0(capsys):
    assert cli.main(["regroup", "api", "--demo"]) == 0
