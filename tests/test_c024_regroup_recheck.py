"""Codex runner-2026-10-15 on dfd0b68: 4. regroup re-checks group membership right before granting."""

from c024util import P, full_routes, page, run_dc

# 4. regroup re-checks group membership right before granting


def test_f4_group_changed_since_plan_refuses_grant(capsys):
    routes = full_routes(
        {
            ("GET", f"{P}/admin/groups/more-members", None): [
                page([{"name": "bob"}]),
                page([{"name": "bob"}, {"name": "mallory"}]),
            ]
        }
    )
    code, sess = run_dc(["regroup", "api", "--apply"], routes)
    assert code not in (0, None)
    assert not any(m == "PUT" for m, *_ in sess.calls)
    assert "changed since the plan" in str(code) + capsys.readouterr().err


def test_f4_unchanged_group_still_applies(capsys):
    code, sess = run_dc(["regroup", "api", "--apply"], full_routes())
    assert code == 0 and any(m == "PUT" for m, *_ in sess.calls)
