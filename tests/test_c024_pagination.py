"""Codex runner-2026-10-15 on dfd0b68: 2. malformed or cyclic pagination is not a complete inventory."""

import pytest
from c024util import P, full_routes, h, run_dc
from fakehttp import Resp

from bbwarden.http import BBWardenError

# 2. malformed or cyclic pagination is not a complete inventory


@pytest.mark.parametrize(
    "body",
    [
        {"isLastPage": True},  # no values
        {"values": "nope", "isLastPage": True},  # values not a list
        {"values": ["a"], "isLastPage": False},  # more pages but no cursor
        {"next": "https://bb.example.com/x?page=2"},  # Cloud page without values
    ],
)
def test_f2_malformed_page_raises(body):
    with pytest.raises(BBWardenError, match="pagination"):
        list(h({("GET", "/x", None): Resp(body=body)}).paginate("x"))


def test_f2_repeated_dc_cursor_raises():
    loop = Resp(body={"values": ["a"], "isLastPage": False, "nextPageStart": 1})
    with pytest.raises(BBWardenError, match="pagination"):
        list(h({("GET", "/x", None): loop}).paginate("x"))


def test_f2_repeated_cloud_next_raises():
    loop = Resp(body={"values": ["x"], "next": "https://bb.example.com/loop?page=2"})
    with pytest.raises(BBWardenError, match="pagination"):
        list(h({("GET", "/loop", None): loop}).paginate("loop"))


def test_f2_cli_exits_nonzero_on_bad_pagination(capsys):
    routes = full_routes(
        {("GET", f"{P}/projects", None): Resp(body={"values": [], "isLastPage": False})}
    )
    code, _ = run_dc(["direct"], routes)
    assert code not in (0, None)
    assert "incomplete pagination" in str(code) + capsys.readouterr().err
