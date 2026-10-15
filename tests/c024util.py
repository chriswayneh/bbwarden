"""Shared helpers for the runner-2026-10-15 Codex finding tests."""

from fakehttp import FakeSession, Resp
from test_live import DC_ENV, P, dc_routes

from bbwarden import cli
from bbwarden.http import Http


def page(vals, **kw):
    return Resp(body={"values": vals, "isLastPage": True, **kw})


def full_routes(extra=None):
    """DC routes with the admin endpoints present, so the inventory is complete."""
    r = dc_routes()
    r[("GET", f"{P}/admin/permissions/users", None)] = page([])
    r[("GET", f"{P}/admin/permissions/groups", None)] = page([])
    r.update(extra or {})
    return r


def run_dc(argv, routes):
    sess = FakeSession(routes)
    try:
        code = cli.main(argv, env=DC_ENV, session_factory=lambda *a: sess)
    except SystemExit as e:
        code = e.code
    return code, sess


def h(routes):
    return Http(FakeSession(routes), "https://bb.example.com", sleep=lambda s: None)
