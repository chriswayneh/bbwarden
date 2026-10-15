"""Review of 528fed5: hosts are normalized per label, exactly like urllib3/requests, so
mixed hosts such as büro.my_host.internal work. Differential checks vs requests."""

import pytest
import requests
from test_idn_ascii import Echo, session

from bbwarden.http import BBWardenError, Http, _origin

MIXED = "https://b\u00fcro.my_host.internal"


def test_mixed_label_host_origin():
    assert _origin(MIXED + "/x") == _origin("https://xn--bro-hoa.my_host.internal/y")
    assert _origin(MIXED) != _origin("https://xn--bro-hoa.my_host.internal.evil")


def test_mixed_label_host_full_request():
    echo = Echo()
    h = Http(session(echo), MIXED, sleep=lambda s: None, timeout=5)
    assert h.get("rest/api/1.0/projects") == {"v": 1}
    assert echo.urls[0].startswith("https://xn--bro-hoa.my_host.internal/")
    assert h.url("https://xn--bro-hoa.my_host.internal/next")
    with pytest.raises(BBWardenError, match="another host"):
        h.url("https://xn--bro-hoa.my_host.internal.evil/next")


def test_urllib3_is_direct_dependency():
    from pathlib import Path

    assert (
        '"urllib3>=1.26,<3"'
        in (Path(__file__).parent.parent / "pyproject.toml").read_text()
    )


HOSTS = [
    "b\u00fcro.my_host.internal",
    "B\u00dcRO.My_Host.internal",
    "\u00fc.-",
    "0..0.\u03c2",
    "0..0.\u03c3",
    "fa\u00df.example",
    "fass.example",
    "xn--fa-hia.example",
    "\u03c2.example",
    "\u03c3.example",
    "bitbucket_server",
    "-b",
    "\u00fc" + "a" * 63 + ".example",
    "[2001:DB8::1]",
    "bb.example.com:8443",
    "BB.EXAMPLE.COM",
]


def prepared_or_none(url):
    try:
        return requests.Request("GET", url).prepare().url
    except (requests.exceptions.InvalidURL, ValueError):
        return None


def check_pair(a, b):
    """No false same-origin: if _origin says equal, requests must send the same authority."""
    pa, pb = prepared_or_none(a), prepared_or_none(b)
    if _origin(a) == _origin(b):
        assert pa is not None and pb is not None
        assert pa.split("/")[2].lower() == pb.split("/")[2].lower()


@pytest.mark.parametrize("host", HOSTS)
def test_differential_self(host):
    """Our URL and what requests sends for it are the same origin, unless requests refuses
    the host, in which case it must never match anything (not even itself)."""
    url = f"https://{host}/x"
    prepared = prepared_or_none(url)
    if prepared is None:
        assert _origin(url) != _origin(url)
    else:
        assert _origin(url) == _origin(prepared)


@pytest.mark.parametrize("a", HOSTS)
@pytest.mark.parametrize("b", HOSTS)
def test_differential_pairs(a, b):
    check_pair(f"https://{a}/x", f"https://{b}/y")


def test_hypothesis_differential():
    hyp = pytest.importorskip("hypothesis")
    st = hyp.strategies
    label = st.text(alphabet="abß_-0.\u00fc\u03c2\u03c3XN", min_size=0, max_size=12)

    @hyp.settings(max_examples=300, deadline=None, derandomize=True)
    @hyp.given(label, label)
    def run(x, y):
        a, b = f"https://{x}/p", f"https://{y}/q"
        check_pair(a, b)
        pa = prepared_or_none(a)
        if pa is not None and _origin(a) == _origin(a):
            assert _origin(a) == _origin(pa)

    run()
