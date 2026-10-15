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
    with pytest.raises(SystemExit, match="--insecure"):
        main(["direct"], env=env, session_factory=lambda *a: sess)
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
    assert "deprecated" in capsys.readouterr().err


def test_crowd_missing_names_new_var():
    with pytest.raises(BBWardenError, match="CROWD_APP_PASSWORD"):
        live.crowd_creds(crowd_env())


def test_security_md():
    s = (ROOT / "SECURITY.md").read_text()
    for needle in ("Reporting a vulnerability", "privately", "Supported versions", "0.2",
                   "https", "secrets", "dry run"):
        assert needle.lower() in s.lower(), needle
