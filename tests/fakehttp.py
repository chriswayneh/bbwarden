"""Tiny fake requests.Session for offline tests."""
import json


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.headers = headers or {}

    def json(self):
        return json.loads(json.dumps(self._body))


class FakeSession:
    """routes: {(METHOD, path_suffix, frozenset(params.items()) or None): Resp or [Resp, ...]}"""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def request(self, method, url, params=None, json=None, timeout=None, allow_redirects=True):
        self.calls.append((method, url, dict(params or {}), json))
        self.allow_redirects = allow_redirects
        key_params = frozenset((params or {}).items())
        for (m, suffix, p), r in self.routes.items():
            if m == method and url.split("?")[0].endswith(suffix) and (p is None or p == key_params):
                if isinstance(r, list):
                    return r.pop(0) if len(r) > 1 else r[0]
                return r
        return Resp(404, {"error": "not found"})
