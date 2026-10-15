"""HTTP layer: retries with backoff, pagination, and safe auth errors."""
import random
import time
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

RETRY_STATUS = (429, 503)


class BBWardenError(Exception):
    """User-facing error. Message must never contain secrets."""

    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


class AuthError(BBWardenError):
    pass


def _retry_after(resp):
    val = resp.headers.get("Retry-After")
    if not val:
        return None
    try:
        return max(0.0, float(val))
    except ValueError:
        try:
            return max(0.0, parsedate_to_datetime(val).timestamp() - time.time())
        except (TypeError, ValueError):
            return None


def _safe_url(url):
    """Drop query string, which could carry tokens."""
    return url.split("?", 1)[0]


IDEMPOTENT = ("GET", "HEAD", "OPTIONS", "PUT", "DELETE")


def _origin(url):
    """(scheme, hostname, port) with default ports filled in."""
    u = urlsplit(url)
    scheme = u.scheme.lower()
    return scheme, (u.hostname or "").lower(), u.port or {"https": 443, "http": 80}.get(scheme)


class Http:
    def __init__(self, session, base_url, max_retries=5, base_delay=1.0, max_delay=60.0,
                 sleep=time.sleep, timeout=30):
        self.session = session
        self.base = base_url.rstrip("/")
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.sleep = sleep
        self.timeout = timeout

    def url(self, path):
        if path.startswith(("http://", "https://")):
            if _origin(path) != _origin(self.base):
                raise BBWardenError(f"refusing to follow link to another host: {_safe_url(path)}")
            return path
        return f"{self.base}/{path.lstrip('/')}"

    def request(self, method, path, **kw):
        url = self.url(path)
        kw.setdefault("timeout", self.timeout)
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.request(method, url, **kw)
            except OSError as e:  # requests exceptions subclass IOError
                raise BBWardenError(f"network error on {method} {_safe_url(url)}: "
                                    f"{type(e).__name__}") from None
            if (resp.status_code in RETRY_STATUS and attempt < self.max_retries
                    and method.upper() in IDEMPOTENT):
                delay = _retry_after(resp)
                if delay is None:
                    delay = self.base_delay * (2 ** attempt) + random.uniform(0, self.base_delay)  # nosec B311 jitter for backoff timing, not security
                self.sleep(min(delay, self.max_delay))
                continue
            break
        code = resp.status_code
        where = f"{method} {_safe_url(url)}"
        if code == 401:
            raise AuthError(f"401 Unauthorized on {where}: check BBWARDEN_USER and BBWARDEN_TOKEN "
                            "(Cloud: app password or API token; Data Center: HTTP access token)", 401)
        if code == 403:
            raise AuthError(f"403 Forbidden on {where}: the credentials work but lack permission "
                            "(needs project/repo admin read; --apply needs admin write)", 403)
        if code in RETRY_STATUS:
            if method.upper() not in IDEMPOTENT:
                raise BBWardenError(f"{code} on {where}: not retried because {method} is not "
                                    "idempotent; check the current state, then re-run")
            raise BBWardenError(f"{code} on {where}: still rate limited after "
                                f"{self.max_retries} retries; try again later")
        if code >= 400:
            raise BBWardenError(f"HTTP {code} on {where}", code)
        return resp

    def get(self, path, **kw):
        resp = self.request("GET", path, **kw)
        try:
            return resp.json()
        except ValueError:
            raise BBWardenError(f"HTTP {resp.status_code} on GET {_safe_url(self.url(path))}: "
                                "response was not JSON (check BBWARDEN_URL points at the "
                                "Bitbucket base URL)") from None

    def paginate(self, path, params=None):
        """Yield items across pages. Handles Cloud (next) and Data Center (isLastPage)."""
        params = dict(params or {})
        url = path
        seen = set()
        while True:
            data = self.get(url, params=params)
            yield from data.get("values", [])
            if "next" in data or "isLastPage" not in data:   # Cloud style
                nxt = data.get("next")
                if not nxt or nxt in seen:
                    return
                seen.add(nxt)
                url, params = nxt, None                   # next URL already carries params
            else:                                         # Data Center style
                if data.get("isLastPage", True) or data.get("nextPageStart") is None:
                    return
                start = data["nextPageStart"]
                if start in seen:
                    return
                seen.add(start)
                params["start"] = start
