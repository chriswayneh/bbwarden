"""QE on cbf750d: ASCII hosts that UTS46 rejects (underscores, leading hyphen) are sent
unchanged by requests and must still be same-origin. Differential check vs requests."""

import pytest
import requests
import requests.adapters

from bbwarden.http import BBWardenError, Http, _origin

ODD_ASCII = [
    "bitbucket_server",
    "my_host.internal",
    "-b",
    "a_b-.example",
    "x" * 64 + ".example",
]


class Echo(requests.adapters.BaseAdapter):
    """Real requests transport: 200 whose final URL is exactly the prepared request URL."""

    def __init__(self, body=None):
        super().__init__()
        self.body = body or {"v": 1}
        self.urls = []

    def send(self, request, **kw):
        import json

        self.urls.append(request.url)
        r = requests.Response()
        r.status_code = 200
        r._content = json.dumps(self.body).encode()
        r.url = request.url
        r.headers["Content-Type"] = "application/json"
        r.request = request
        return r

    def close(self):
        pass


def session(adapter):
    s = requests.Session()
    s.max_redirects = 0
    s.trust_env = False
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


@pytest.mark.parametrize(
    "host", ["bitbucket_server:7990", "my_host.internal", "BitBucket_Server"]
)
def test_underscore_host_request_accepted(host):
    h = Http(session(Echo()), f"https://{host}", sleep=lambda s: None, timeout=5)
    assert h.get("rest/api/1.0/projects") == {"v": 1}


def test_underscore_host_pagination_link_accepted():
    base = "https://my_host.internal"
    h = Http(session(Echo()), base, sleep=lambda s: None, timeout=5)
    assert h.url(base + "/rest/x?page=2") == base + "/rest/x?page=2"
    assert h.url("https://MY_HOST.internal/next") == "https://MY_HOST.internal/next"
    with pytest.raises(BBWardenError, match="another host"):
        h.url("https://my_host.internal.evil/next")


@pytest.mark.parametrize(
    "a,b,same",
    [
        ("https://xn--fa-hia.example", "https://fa\u00df.example", True),
        ("https://fa\u00df.example", "https://XN--FA-HIA.example", True),
        ("https://fass.example", "https://fa\u00df.example", False),
        ("https://fa\u00df.example", "https://fass.example", False),
        ("https://xn--4xa.example", "https://\u03c2.example", False),
        ("https://xn--3xa.example", "https://\u03c2.example", True),
    ],
)
def test_mixed_ascii_and_unicode(a, b, same):
    assert (_origin(a) == _origin(b)) is same


HOSTS = ODD_ASCII + [
    "bb.example.com",
    "BB.Example.COM",
    "localhost",
    "127.0.0.1",
    "xn--bcher-kva.example",
    "b\u00fccher.example",
    "B\u00dcCHER.example",
    "fa\u00df.example",
    "fass.example",
    "\u03c3.example",
    "\u03c2.example",
    "[2001:db8::1]",
]


@pytest.mark.parametrize("host", HOSTS)
def test_differential_vs_requests(host):
    """_origin of the URL we build equals _origin of what requests actually sends, and the
    hostname equals the prepared netloc (lowercased)."""
    url = f"https://{host}/x"
    try:
        prepared = requests.Request("GET", url).prepare().url
    except requests.exceptions.InvalidURL:
        pytest.skip(f"requests itself refuses {host!r}")
    assert _origin(url) == _origin(prepared)
    netloc = prepared.split("/")[2].lower()
    want = netloc[1:-1] if netloc.startswith("[") else netloc
    assert _origin(prepared)[1] == want
