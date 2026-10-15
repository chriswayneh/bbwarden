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


def check(msg, status):
    assert f"redirect refused: {status} to evil.example.net" in msg
    assert "s3cr3t" not in msg and "/steal" not in msg


def test_bitbucket_path_real_session(server):
    srv, base = server
    # Direct construction bypasses creds_from_env's https check for the test only.
    h = Http(live.harden_session(requests.Session()), base, sleep=lambda s: None)
    with pytest.raises(BBWardenError) as e:
        h.get("rest/api/1.0/projects")
    check(str(e.value), srv.status)


def test_crowd_path_real_session(server):
    srv, base = server
    env = {"CROWD_URL": base, "CROWD_APP": "app", "CROWD_APP_PASSWORD": "pw"}
    crowd = live.crowd_from_env(env, session_factory=lambda: live.harden_session(requests.Session()),
                                insecure=True)
    with pytest.raises(BBWardenError) as e:
        live.crowd_status(crowd, ["bob"])
    check(str(e.value), srv.status)
