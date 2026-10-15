"""Review of 65a1ee6: hard-coded expected wire hosts (not derived from requests at test
time), and _origin fails closed on any error."""

import pytest
import requests

from bbwarden import http as bhttp
from bbwarden.http import _origin


@pytest.mark.parametrize(
    "host,want",
    [
        ("b\u00fccher.example", "xn--bcher-kva.example"),
        ("fa\u00df.example", "xn--fa-hia.example"),
        ("\u03c2.example", "xn--3xa.example"),
        ("\u03c3.example", "xn--4xa.example"),
        ("b\u00fcro.my_host.internal", "xn--bro-hoa.my_host.internal"),
        ("BitBucket_Server", "bitbucket_server"),
        ("[FE80::1]", "fe80::1"),
        ("BB.Example.COM:8443", "bb.example.com"),
    ],
)
def test_expected_wire_host(host, want):
    assert _origin(f"https://{host}/x")[1] == want


def test_origin_fails_closed_on_unexpected_error(monkeypatch):
    def boom(self, url, params):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(requests.models.PreparedRequest, "prepare_url", boom)
    a = _origin("https://bb.example.com/x")
    assert a != _origin("https://bb.example.com/x")
    h = bhttp.Http(None, "https://bb.example.com")
    with pytest.raises(bhttp.BBWardenError, match="another host"):
        h.url("https://bb.example.com/next")
