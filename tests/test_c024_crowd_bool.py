"""Codex runner-2026-10-15 on dfd0b68: 9. Crowd active flag must be a real boolean."""

import pytest
from c024util import h
from fakehttp import Resp

from bbwarden import live
from bbwarden.http import BBWardenError

# 9. Crowd active flag must be a real boolean


@pytest.mark.parametrize(
    "body", [{"active": "false"}, {"active": "true"}, {}, {"active": 1}]
)
def test_f9_crowd_non_boolean_active_refused(body):
    crowd = h({("GET", "/rest/usermanagement/1/user", None): Resp(body=body)})
    with pytest.raises(BBWardenError, match="active"):
        live.crowd_status(crowd, ["dave"])


def test_f9_crowd_boolean_active_ok():
    crowd = h(
        {
            (
                "GET",
                "/rest/usermanagement/1/user",
                frozenset({("username", "a")}),
            ): Resp(body={"active": True}),
            (
                "GET",
                "/rest/usermanagement/1/user",
                frozenset({("username", "b")}),
            ): Resp(body={"active": False}),
        }
    )
    assert live.crowd_status(crowd, ["a", "b"]) == {"a": True, "b": False}
