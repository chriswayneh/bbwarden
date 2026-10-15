"""Secure-defaults tests: https only unless --insecure, CROWD_APP_PASSWORD rename, SECURITY.md."""
from pathlib import Path

import pytest
from fakehttp import FakeSession, Resp

from bbwarden import live
from bbwarden.cli import main
from bbwarden.http import BBWardenError

ROOT = Path(__file__).resolve().parent.parent
BASE = {"BBWARDEN_USER": "u", "BBWARDEN_TOKEN": "t"}


def creds(url, **kw):
    return live.creds_from_env({**BASE, "BBWARDEN_URL": url}, **kw)


@pytest.mark.parametrize("url", ["http://localhost:7990", "http://127.0.0.1", "http://bb.example.com"])
def test_http_refused_without_insecure(url):
    with pytest.raises(BBWardenError, match="--insecure"):
        creds(url)


def test_http_allowed_with_insecure_and_warns(capsys):
    assert creds("http://bb.example.com", insecure=True)[0] == "http://bb.example.com"
    assert "WARNING" in capsys.readouterr().err


def test_insecure_flag_reaches_backend(capsys):
    page = lambda v: Resp(body={"values": v, "isLastPage": True})
    sess = FakeSession({("GET", "/rest/api/1.0/projects", None): page([]),
                        ("GET", "/rest/api/1.0/admin/users", None): page([])})
    env = {**BASE, "BBWARDEN_URL": "http://localhost:7990"}
    with pytest.raises(SystemExit) as e:
        main(["direct"], env=env, session_factory=lambda *a: sess)
    assert e.value.code == 2
    assert "error: BBWARDEN_URL must use https://" in capsys.readouterr().err
    main(["direct", "--insecure"], env=env, session_factory=lambda *a: sess)
    assert "WARNING" in capsys.readouterr().err


def crowd_env(**extra):
    return {"CROWD_URL": "https://crowd.example.com", "CROWD_APP": "app", **extra}


def test_crowd_http_refused_without_insecure():
    with pytest.raises(BBWardenError, match="--insecure"):
        live.crowd_from_env({**crowd_env(CROWD_APP_PASSWORD="p"), "CROWD_URL": "http://crowd"},
                            session_factory=lambda: None)
    live.crowd_from_env({**crowd_env(CROWD_APP_PASSWORD="p"), "CROWD_URL": "http://crowd"},
                        session_factory=lambda: None, insecure=True)


def test_crowd_app_password_new_name(capsys):
    assert live.crowd_creds(crowd_env(CROWD_APP_PASSWORD="new")) == ("https://crowd.example.com", "app", "new")
    assert "deprecated" not in capsys.readouterr().err


def test_crowd_password_old_name_warns(capsys):
    assert live.crowd_creds(crowd_env(CROWD_PASSWORD="old"))[2] == "old"
    err = capsys.readouterr().err
    assert "CROWD_PASSWORD is deprecated" in err and "old" not in err.split("deprecated")[1]


def test_crowd_new_name_wins(capsys):
    assert live.crowd_creds(crowd_env(CROWD_PASSWORD="old", CROWD_APP_PASSWORD="new"))[2] == "new"
    assert "ignored" in capsys.readouterr().err


def test_crowd_missing_names_new_var():
    with pytest.raises(BBWardenError, match="CROWD_APP_PASSWORD"):
        live.crowd_creds(crowd_env())


def test_security_md():
    s = (ROOT / "SECURITY.md").read_text()
    for needle in ("Reporting a vulnerability", "privately", "Supported versions", "0.2",
                   "https", "secrets", "dry run"):
        assert needle.lower() in s.lower(), needle


# review on 1455b0c
@pytest.mark.parametrize("url", ["https:x", "https://", "https:///path", "http://"])
def test_url_without_hostname_refused(url):
    with pytest.raises(BBWardenError, match="no hostname"):
        live.creds_from_env({**BASE, "BBWARDEN_URL": url}, insecure=True)


def test_crowd_url_without_hostname_refused():
    with pytest.raises(BBWardenError, match="CROWD_URL has no hostname"):
        live.crowd_from_env({**crowd_env(CROWD_APP_PASSWORD="p"), "CROWD_URL": "https://"},
                            session_factory=lambda: None)


def test_both_crowd_passwords_note_not_deprecation_warning(capsys):
    live.crowd_creds(crowd_env(CROWD_PASSWORD="old", CROWD_APP_PASSWORD="new"))
    err = capsys.readouterr().err
    assert "deprecated" not in err
    assert "NOTE: CROWD_PASSWORD is ignored because CROWD_APP_PASSWORD is set" in err


def test_security_md_private_contact_and_no_sla():
    s = (ROOT / "SECURITY.md").read_text()
    assert "5 business days" not in s and "as soon as practical" in s
    assert "@chriswayneh" in s and "when the repository goes public" in s
    assert 'Security tab, "Report a vulnerability"), or' not in s


# QE on 1cad405: config errors exit 2
@pytest.mark.parametrize("env,needle", [
    ({**BASE, "BBWARDEN_URL": "http://bb.example.com"}, "must use https://"),
    ({**BASE, "BBWARDEN_URL": "https://"}, "no hostname"),
    ({"BBWARDEN_URL": "https://bb.example.com"}, "missing BBWARDEN_USER, BBWARDEN_TOKEN"),
    ({**BASE, "BBWARDEN_URL": "https://bitbucket.org"}, "missing BBWARDEN_WORKSPACE"),
])
def test_config_errors_exit_2_on_stderr(env, needle, capsys):
    with pytest.raises(SystemExit) as e:
        main(["direct"], env=env, session_factory=lambda *a: None)
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ") and needle in err and "t\n" not in err


def test_runtime_errors_keep_exit_1(capsys):
    from bbwarden import core
    with pytest.raises(SystemExit) as e:
        main(["who", "nope", "--demo"])
    assert e.value.code != 2 and "unknown" in str(e.value)
    assert core is not None


# redirects are refused
from bbwarden.http import Http


@pytest.mark.parametrize("loc,host", [("http://bb.example.com/x", "bb.example.com"),
                                      ("https://evil.example.net/steal", "evil.example.net")])
def test_bitbucket_redirect_refused(loc, host):
    sess = FakeSession({("GET", "/x", None): Resp(301, headers={"Location": loc + "?token=s3cr3t"})})
    h = Http(sess, "https://bb.example.com", sleep=lambda s: None)
    with pytest.raises(BBWardenError) as e:
        h.get("x")
    msg = str(e.value)
    assert "301" in msg and "redirect" in msg and host in msg
    assert "s3cr3t" not in msg and "/steal" not in msg
    assert sess.allow_redirects is False


@pytest.mark.parametrize("loc", ["http://crowd.example.com/u", "https://evil.example.net/u"])
def test_crowd_redirect_refused(loc):
    sess = FakeSession({("GET", "/rest/usermanagement/1/user", None): Resp(302, headers={"Location": loc})})
    crowd = live.crowd_from_env(crowd_env(CROWD_APP_PASSWORD="p"), session_factory=lambda: sess)
    with pytest.raises(BBWardenError, match="redirect refused: 302"):
        live.crowd_status(crowd, ["bob"])
    assert sess.allow_redirects is False


def test_followed_redirect_detected_by_history():
    followed = Resp(200, body={})
    followed.url = "https://evil.example.net/x"
    followed.history = [Resp(301)]
    sess = FakeSession({("GET", "/x", None): followed})
    with pytest.raises(BBWardenError, match="redirect"):
        Http(sess, "https://bb.example.com").get("x")


def test_sessions_disable_redirects():
    import requests
    s = live.harden_session(requests.Session())
    assert s.max_redirects == 0


# 0.2.1 version hygiene
def test_version_021():
    import re

    from bbwarden import __version__
    assert __version__ == "0.2.1"
    c = (ROOT / "CHANGELOG.md").read_text()
    assert re.search(r"^## \[0\.2\.1\] - 2026-10-15", c, re.MULTILINE) and "[Unreleased]" not in c
    assert "**Breaking**" in c.split("## [0.2.0]")[0]
    sec = (ROOT / "SECURITY.md").read_text()
    assert "0.2.1" in sec and "| 0.2.1 |" in sec
    assert "bbwarden 0.2.1" in (ROOT / "README.md").read_text()
