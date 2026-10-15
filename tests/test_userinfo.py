"""URLs with embedded credentials: refused up front, and never echoed in any message."""

import pytest
from fakehttp import FakeSession, Resp

from bbwarden import live
from bbwarden.cli import main
from bbwarden.http import BBWardenError, Http, _safe_url

SECRET = (
    "pa55-" + "S3CRET" + "-tok"
)  # built at runtime so secret scanners do not flag it
CRED_BASE = f"https://user:{SECRET}@bb.example.com"


@pytest.mark.parametrize(
    "url,want",
    [
        (
            f"https://user:{SECRET}@bb.example.com/rest/x?token={SECRET}#frag",
            "https://bb.example.com/rest/x",
        ),
        (f"https://{SECRET}@bb.example.com:8443/p", "https://bb.example.com:8443/p"),
        (
            f"https://u:{SECRET}@[2001:db8::1]:7990/rest?a=1",
            "https://[2001:db8::1]:7990/rest",
        ),
        ("https://[::1]/x", "https://[::1]/x"),
        ("http://bb.example.com", "http://bb.example.com"),
    ],
)
def test_safe_url_drops_userinfo_query_fragment(url, want):
    assert _safe_url(url) == want


def http(routes):
    return Http(FakeSession(routes), CRED_BASE, sleep=lambda s: None, timeout=5)


def test_redirect_message_no_secret():
    h = http(
        {
            ("GET", "/x", None): Resp(
                301, headers={"Location": "https://evil.example.net/"}
            )
        }
    )
    with pytest.raises(BBWardenError) as e:
        h.get("x")
    assert "redirect refused" in str(e.value) and SECRET not in str(e.value)


def test_401_message_no_secret():
    with pytest.raises(BBWardenError) as e:
        http({("GET", "/x", None): Resp(401)}).get("x")
    assert "401" in str(e.value) and SECRET not in str(e.value)


def test_network_error_no_secret():
    class Boom:
        def request(self, *a, **k):
            raise ConnectionError("boom")

    with pytest.raises(BBWardenError) as e:
        Http(Boom(), CRED_BASE, timeout=5).get("x")
    assert "network error" in str(e.value) and SECRET not in str(e.value)


@pytest.mark.parametrize(
    "url",
    [
        CRED_BASE,
        f"https://{SECRET}@bb.example.com",
        f"https://user:{SECRET}@[2001:db8::1]:7990",
    ],
)
def test_bbwarden_url_with_credentials_refused(url, capsys):
    env = {"BBWARDEN_URL": url, "BBWARDEN_USER": "u", "BBWARDEN_TOKEN": "t"}
    with pytest.raises(SystemExit) as e:
        main(["direct"], env=env, session_factory=lambda *a: None)
    assert e.value.code == 2
    cap = capsys.readouterr()
    assert cap.err.startswith("error: BBWARDEN_URL must not contain credentials")
    assert SECRET not in cap.err and SECRET not in cap.out


def test_crowd_url_with_credentials_refused():
    env = {
        "CROWD_URL": f"https://app:{SECRET}@crowd.example.com",
        "CROWD_APP": "a",
        "CROWD_APP_PASSWORD": "p",
    }
    with pytest.raises(BBWardenError) as e:
        live.crowd_from_env(env, session_factory=lambda: None)
    assert "CROWD_URL must not contain credentials" in str(
        e.value
    ) and SECRET not in str(e.value)


def test_crowd_url_with_credentials_cli_exit_2(capsys):
    from test_live import DC_ENV, dc_routes

    env = {
        **DC_ENV,
        "CROWD_URL": f"https://app:{SECRET}@crowd.example.com",
        "CROWD_APP": "a",
        "CROWD_APP_PASSWORD": "p",
    }
    with pytest.raises(SystemExit) as e:
        main(
            ["orphans", "--idp", "crowd"],
            env=env,
            session_factory=lambda *a: FakeSession(dc_routes()),
        )
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "CROWD_URL must not contain credentials" in err and SECRET not in err
