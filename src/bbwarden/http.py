"""HTTP layer: retries with backoff, pagination, and safe auth errors."""

import random
import time
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import requests
from urllib3.util import parse_url

RETRY_STATUS = (429, 503)


class BBWardenError(Exception):
    """User-facing error. Message must never contain secrets."""

    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


class ConfigError(BBWardenError):
    """Bad or missing configuration (environment, URL). The CLI exits with code 2."""


class AuthError(BBWardenError):
    pass


class MissingConfig(ConfigError, AuthError):
    """A required credential or setting is not set."""


class ManualStep(BBWardenError):
    """The step cannot be done by API and must be done by hand (e.g. Cloud workspace owner)."""


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
    """URL for messages: scheme, host, port and path only. Userinfo, query and fragment can
    carry credentials or tokens, so they are dropped. IPv6 hosts keep their brackets."""
    try:
        u = urlsplit(url)
        host = u.hostname or ""
        port = u.port
    except ValueError:
        return "<invalid URL>"
    if u.scheme and not u.netloc:  # 'https:u:p@h' would otherwise echo its path
        return "<invalid URL>"
    if ":" in host:
        host = f"[{host}]"
    netloc = f"{host}:{port}" if port is not None else host
    return f"{u.scheme}://{netloc}{u.path}" if u.scheme else f"{netloc}{u.path}"


IDEMPOTENT = ("GET", "HEAD", "OPTIONS", "PUT", "DELETE")


def _origin(url):
    """(scheme, host, port) exactly as requests will send it, default ports filled in.

    The URL is prepared by requests itself (PreparedRequest.prepare_url) and the result
    parsed with urllib3's parse_url, so the comparison uses the wire form: ASCII labels
    are kept (bitbucket_server, my_host.internal), non-ASCII labels are IDNA2008-encoded
    (büro.my_host.internal is sent as xn--bro-hoa.my_host.internal), and the host is
    lowercased. Hosts that only IDNA2003 would merge (faß vs fass, ς vs σ) stay different.
    A URL that requests refuses, that has no host, or that raises any error gets a fresh object() as host, which
    equals nothing, so it is never treated as the same origin."""
    # A fresh object() per call is what guarantees no match: it compares equal only to
    # itself, and each _origin call builds a new one, so two failed URLs never compare equal,
    # not even the same URL twice.
    never = ("", object(), None)
    try:
        prepared = requests.models.PreparedRequest()
        prepared.prepare_url(url, None)
        u = parse_url(prepared.url or "")
        host = (u.host or "").lower()
        port = u.port
    except Exception:  # noqa: BLE001 - fail closed: any error means "not the same origin"
        return never
    if not host:
        return never
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]  # IPv6 literal, same form as urlsplit().hostname
    scheme = (u.scheme or "").lower()
    return (scheme, host, port or {"https": 443, "http": 80}.get(scheme))


def _redirect_error(status, location, where):
    """Status and target hostname only: never the path, query or credentials."""
    host = urlsplit(location or "").hostname or "unknown host"
    head = (
        f"redirect refused: {status} to {host}"
        if status
        else f"redirect refused to {host}"
    )
    return BBWardenError(
        f"{head} on {where}; set the URL to the final https:// address", status
    )


class Http:
    def __init__(
        self,
        session,
        base_url,
        max_retries=5,
        base_delay=1.0,
        max_delay=60.0,
        sleep=time.sleep,
        timeout=30,
    ):
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
                raise BBWardenError(
                    f"refusing to follow link to another host: {_safe_url(path)}"
                )
            return path
        return f"{self.base}/{path.lstrip('/')}"

    def request(self, method, path, **kw):
        url = self.url(path)
        kw.setdefault("timeout", self.timeout)
        kw["allow_redirects"] = (
            False  # never follow: a redirect could carry credentials elsewhere
        )
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.request(method, url, **kw)
            except requests.TooManyRedirects as e:
                # Sessions have max_redirects=0, so a redirect seen by requests itself lands here.
                r = e.response
                status = r.status_code if r is not None else None
                loc = r.headers.get("Location", "") if r is not None else ""
                raise _redirect_error(
                    status, loc, f"{method} {_safe_url(url)}"
                ) from None
            except OSError as e:  # requests exceptions subclass IOError
                raise BBWardenError(
                    f"network error on {method} {_safe_url(url)}: {type(e).__name__}"
                ) from None
            if (
                resp.status_code in RETRY_STATUS
                and attempt < self.max_retries
                and method.upper() in IDEMPOTENT
            ):
                delay = _retry_after(resp)
                if delay is None:
                    jitter = random.uniform(0, self.base_delay)  # nosec B311 backoff jitter, not security
                    delay = self.base_delay * (2**attempt) + jitter
                self.sleep(min(delay, self.max_delay))
                continue
            break
        code = resp.status_code
        where = f"{method} {_safe_url(url)}"
        history = getattr(resp, "history", None)
        final = getattr(resp, "url", None)
        if (
            300 <= code < 400
            or history
            or (isinstance(final, str) and final and _origin(final) != _origin(url))
        ):
            loc = (
                resp.headers.get("Location")
                or (final if isinstance(final, str) else "")
                or ""
            )
            shown = (
                code
                if 300 <= code < 400
                else history[0].status_code
                if history
                else code
            )
            raise _redirect_error(shown, loc, where)
        if code == 401:
            raise AuthError(
                f"401 Unauthorized on {where}: check BBWARDEN_USER and BBWARDEN_TOKEN "
                "(Cloud: app password or API token; Data Center: HTTP access token)",
                401,
            )
        if code == 403:
            raise AuthError(
                f"403 Forbidden on {where}: the credentials work but lack permission "
                "(needs project/repo admin read; --apply needs admin write)",
                403,
            )
        if code in RETRY_STATUS:
            if method.upper() not in IDEMPOTENT:
                raise BBWardenError(
                    f"{code} on {where}: not retried because {method} is not "
                    "idempotent; check the current state, then re-run"
                )
            raise BBWardenError(
                f"{code} on {where}: still rate limited after "
                f"{self.max_retries} retries; try again later"
            )
        if code >= 400:
            raise BBWardenError(f"HTTP {code} on {where}", code)
        return resp

    def get(self, path, **kw):
        resp = self.request("GET", path, **kw)
        try:
            return resp.json()
        except ValueError:
            raise BBWardenError(
                f"HTTP {resp.status_code} on GET {_safe_url(self.url(path))}: "
                "response was not JSON (check BBWARDEN_URL points at the "
                "Bitbucket base URL)"
            ) from None

    def paginate(self, path, params=None):
        """Yield items across pages. Handles Cloud (next) and Data Center (isLastPage).

        A page without a "values" list, a Data Center page that says more pages follow but
        gives no cursor, and a repeated cursor or next link all raise: a partial list must
        never be mistaken for the full inventory that regroup and offboard rely on."""
        params = dict(params or {})
        url = path
        seen = set()
        where = _safe_url(self.url(path))

        def broken(why):
            return BBWardenError(
                f"incomplete pagination on GET {where}: {why}; refusing to continue on a "
                "partial result"
            )

        while True:
            data = self.get(url, params=params)
            values = data.get("values") if isinstance(data, dict) else None
            if not isinstance(values, list):
                raise broken("page has no list of values")
            yield from values
            if "next" in data or "isLastPage" not in data:  # Cloud style
                nxt = data.get("next")
                if not nxt:
                    return
                if nxt in seen:
                    raise broken("next link repeats")
                seen.add(nxt)
                url, params = nxt, None  # next URL already carries params
            else:  # Data Center style
                if data.get("isLastPage") is True:
                    return
                start = data.get("nextPageStart")
                if start is None:
                    raise broken("more pages announced but no nextPageStart")
                if start in seen:
                    raise broken("nextPageStart repeats")
                seen.add(start)
                params["start"] = start
