"""Redirect handling against a real requests.Session and a local http.server."""

import http.server
import threading

import pytest
import requests

from bbwarden import live
from bbwarden.http import BBWardenError, Http


class Redirector(http.server.BaseHTTPRequestHandler):
    status = 301

    def do_GET(self):
        self.send_response(self.server.status)
        self.send_header("Location", "https://evil.example.net/steal?token=s3cr3t")
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture(params=[301, 302])
def server(request):
    srv = http.server.HTTPServer(("127.0.0.1", 0), Redirector)
    srv.status = request.param
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()
    srv.server_close()


def real_session():
    s = live.harden_session(requests.Session())
    s.trust_env = False  # ignore proxy and netrc settings from the environment
    return s


def check(msg, status):
    assert f"redirect refused: {status} to evil.example.net" in msg
    assert "s3cr3t" not in msg and "/steal" not in msg


def test_bitbucket_path_real_session(server):
    srv, base = server
    # Direct construction bypasses creds_from_env's https check for the test only.
    h = Http(real_session(), base, sleep=lambda s: None, timeout=5)
    with pytest.raises(BBWardenError) as e:
        h.get("rest/api/1.0/projects")
    check(str(e.value), srv.status)


def test_crowd_path_real_session(server):
    srv, base = server
    env = {"CROWD_URL": base, "CROWD_APP": "app", "CROWD_APP_PASSWORD": "pw"}
    crowd = live.crowd_from_env(
        env,
        session_factory=lambda: live.harden_session(requests.Session()),
        insecure=True,
    )
    with pytest.raises(BBWardenError) as e:
        live.crowd_status(crowd, ["bob"])
    check(str(e.value), srv.status)


class ForceFollow:
    """Wrapper that overrides allow_redirects=True, like a library path that follows redirects,
    so the hardened session's max_redirects=0 raises a real TooManyRedirects."""

    def __init__(self, inner):
        self.inner = inner
        self.saw_too_many = False

    def request(self, method, url, **kw):
        kw["allow_redirects"] = True
        try:
            return self.inner.request(method, url, **kw)
        except requests.TooManyRedirects:
            self.saw_too_many = True
            raise


def test_too_many_redirects_branch_real(server):
    srv, base = server
    sess = ForceFollow(real_session())
    h = Http(sess, base, sleep=lambda s: None, timeout=5)
    with pytest.raises(BBWardenError) as e:
        h.get("x")
    assert sess.saw_too_many
    check(str(e.value), srv.status)


def test_too_many_redirects_without_response():
    class NoResponse:
        def request(self, *a, **k):
            raise requests.TooManyRedirects("Exceeded 0 redirects.")

    with pytest.raises(BBWardenError) as e:
        Http(NoResponse(), "https://bb.example.com", timeout=5).get("x")
    msg = str(e.value)
    assert msg.startswith("redirect refused to unknown host") and "None" not in msg
