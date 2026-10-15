"""Codex runner-2026-10-15 on dfd0b68: 3. optional discovery that failed means the inventory is incomplete."""

from c024util import full_routes, run_dc
from test_live import dc_routes

# 3. optional discovery that failed means the inventory is incomplete


def test_f3_incomplete_inventory_offboard_apply_exit_3(capsys):
    code, _ = run_dc(
        ["offboard", "bob", "--apply"], dc_routes()
    )  # no admin routes: 404
    assert code == 3
    err = capsys.readouterr().err
    assert "INCOMPLETE" in err and "global admin users not loaded" in err


def test_f3_incomplete_inventory_dry_run_exit_3(capsys):
    code, _ = run_dc(["offboard", "bob"], dc_routes())
    assert code == 3


def test_f3_complete_inventory_exit_0(capsys):
    code, _ = run_dc(["offboard", "bob"], full_routes())
    assert code == 0
