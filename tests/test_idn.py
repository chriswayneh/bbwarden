"""IDN hosts: requests reports the final URL punycoded, so the origin check must compare
IDNA-normalized hostnames. Invalid IDNA hosts are never treated as same-origin."""

import pytest
from fakehttp import FakeSession, Resp

from bbwarden.http import BBWardenError, Http, _origin, _safe_url

UNI = "https://b\u00fccher.example"
PUNY = "https://xn--bcher-kva.example"


def http(base, routes):
    return Http(FakeSession(routes), base, sleep=lambda s: None, timeout=5)


def test_origin_unicode_equals_punycode():
    assert _origin(UNI + "/x") == _origin(PUNY + "/y")
    assert _origin("https://B\u00dcCHER.example") == _origin(PUNY)


def test_unicode_base_punycode_final_accepted():
    ok = Resp(200, body={"v": 1})
    ok.url = PUNY + "/rest/x"
    assert http(UNI, {("GET", "/rest/x", None): ok}).get("rest/x") == {"v": 1}


def test_different_idn_final_refused():
    other = Resp(200, body={})
    other.url = "https://xn--bcher-kva.example.net/rest/x"  # bücher.example.net
    with pytest.raises(BBWardenError, match="redirect refused"):
        http(UNI, {("GET", "/rest/x", None): other}).get("rest/x")
    homograph = Resp(200, body={})
    homograph.url = "https://xn--bchr-0ra.example/rest/x"
    with pytest.raises(BBWardenError, match="redirect refused"):
        http(UNI, {("GET", "/rest/x", None): homograph}).get("rest/x")


@pytest.mark.parametrize("base,link", [(UNI, PUNY + "/next"), (PUNY, UNI + "/next")])
def test_url_link_check_idn_same_host(base, link):
    assert http(base, {}).url(link) == link


def test_url_link_check_idn_other_host_refused():
    with pytest.raises(BBWardenError, match="another host"):
        http(UNI, {}).url("https://xn--bchr-0ra.example/next")


def test_invalid_idna_host_never_same_origin():
    bad = "https://" + "a" * 64 + ".example"  # label too long for IDNA
    assert _origin(bad) != _origin(bad)
    with pytest.raises(BBWardenError, match="another host"):
        http(bad, {}).url(bad + "/next")


def test_ipv6_and_ascii_untouched():
    assert _origin("https://[2001:DB8::1]:8443/x") == ("https", "2001:db8::1", 8443)
    assert _origin("HTTPS://BB.Example.com/x") == ("https", "bb.example.com", 443)


def test_safe_url_idn():
    assert _safe_url("https://u:p@B\u00dccher.example/x?q=1#f") == UNI + "/x"
    assert _safe_url(PUNY + "/x?token=t") == PUNY + "/x"


# Regression guards (credential and redirect leaks). Existing coverage:
# tests/test_userinfo.py::test_bbwarden_url_with_credentials_refused (exit 2, no echo),
# tests/test_userinfo.py::test_redirect_message_no_secret, tests/test_secure.py::
# test_bitbucket_redirect_refused (query not echoed). This adds userinfo, query and
# fragment in the Location header, with an IDN base.
def test_redirect_message_no_userinfo_query_fragment():
    loc = "https://user:pw0rd@evil.example.net/p4th?token=S3CRETQ#fr4g"
    h = http(UNI, {("GET", "/x", None): Resp(302, headers={"Location": loc})})
    with pytest.raises(BBWardenError) as e:
        h.get("x")
    msg = str(e.value)
    assert "evil.example.net" in msg
    for bit in ("user", "pw0rd", "p4th", "S3CRETQ", "fr4g"):
        assert bit not in msg


# IDNA2008/UTS46 (what requests uses) keeps sharp s and final sigma distinct; IDNA2003
# maps them to "ss" and "σ", which would wrongly treat another host as the same origin.
DEVIANT = [
    ("https://fa\u00df.example", "https://fass.example"),
    ("https://\u03c3.example", "https://\u03c2.example"),
]
BOTH_WAYS = DEVIANT + [(b, a) for a, b in DEVIANT]


@pytest.mark.parametrize("base,other", BOTH_WAYS)
def test_deviation_chars_url_refused(base, other):
    import requests

    for link in (
        other + "/next",
        requests.Request("GET", other + "/next").prepare().url,
    ):
        with pytest.raises(BBWardenError, match="another host"):
            http(base, {}).url(link)


@pytest.mark.parametrize("base,other", BOTH_WAYS)
def test_deviation_chars_final_url_refused(base, other):
    import requests

    resp = Resp(200, body={})
    resp.url = requests.Request("GET", other + "/rest/x").prepare().url
    with pytest.raises(BBWardenError, match="redirect refused"):
        http(base, {("GET", "/rest/x", None): resp}).get("rest/x")


@pytest.mark.parametrize(
    "host",
    [
        "b\u00fccher.example",
        "fa\u00df.example",
        "\u03c3.example",
        "\u03c2.example",
        "BB.Example.com",
    ],
)
def test_origin_matches_requests_prepared_url(host):
    import requests

    prepared = requests.Request("GET", f"https://{host}/x").prepare().url
    assert _origin(f"https://{host}/x") == _origin(prepared)
    assert _origin(prepared)[1] == prepared.split("/")[2]


def test_idna_is_direct_dependency():
    from pathlib import Path

    text = (Path(__file__).parent.parent / "pyproject.toml").read_text()
    assert '"idna>=2.5,<4"' in text
