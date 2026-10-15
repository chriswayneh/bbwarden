"""Codex runner-2026-10-15 on dfd0b68: 1. non-admin global permissions survive offboarding."""

from c024util import P, full_routes, page, run_dc
from fakehttp import Resp

# 1. non-admin global permissions survive offboarding


def global_routes():
    return full_routes(
        {
            ("GET", f"{P}/admin/permissions/users", None): page(
                [
                    {"user": {"name": "bob"}, "permission": "PROJECT_CREATE"},
                    {"user": {"name": "carl"}, "permission": "LICENSED_USER"},
                ]
            ),
            ("DELETE", f"{P}/admin/permissions/users", None): Resp(204),
        }
    )


def test_f1_offboard_plans_non_admin_global_permission(capsys):
    code, _ = run_dc(["offboard", "bob"], global_routes())
    out = capsys.readouterr().out
    assert code == 0
    assert "remove all global permissions" in out and "PROJECT_CREATE" in out


def test_f1_user_with_only_a_global_permission_is_known(capsys):
    code, _ = run_dc(["offboard", "carl"], global_routes())
    assert code == 0 and "LICENSED_USER" in capsys.readouterr().out


def test_f1_apply_removes_global_permission(capsys):
    code, sess = run_dc(["offboard", "bob", "--apply"], global_routes())
    assert code == 0
    assert ("DELETE", {"name": "bob"}) in [
        (m, p) for m, u, p, _ in sess.calls if u.endswith("/admin/permissions/users")
    ]


def test_f1_who_still_counts_only_admin_levels(capsys):
    run_dc(["who", "api"], global_routes())
    assert "global:" not in capsys.readouterr().out
