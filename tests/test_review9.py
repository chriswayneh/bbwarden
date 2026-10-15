"""Review minors on 724c2d1: invalid netloc, query/fragment in base URLs, no str() of
unexpected exceptions in partial-apply output."""

import logging

import pytest
from test_round8 import Backend, run, ws_root

from bbwarden import cli, core, live
from bbwarden.http import _safe_url

SECRET = (
    "pa55-" + "S3CRET" + "-tok"
)  # built at runtime so secret scanners do not flag it


@pytest.mark.parametrize(
    "url", [f"https:u:{SECRET}@h", "https:", f"http:/{SECRET}@h/x"]
)
def test_safe_url_scheme_without_netloc_is_invalid(url):
    assert _safe_url(url) == "<invalid URL>"


@pytest.mark.parametrize(
    "url",
    [
        f"https://bb.example.com/?token={SECRET}",
        f"https://bb.example.com/#{SECRET}",
        "https://bb.example.com/?",
        "https://bb.example.com/#",
    ],
)
def test_bbwarden_url_query_or_fragment_refused(url, capsys):
    env = {"BBWARDEN_URL": url, "BBWARDEN_USER": "u", "BBWARDEN_TOKEN": "t"}
    with pytest.raises(SystemExit) as e:
        cli.main(["direct"], env=env, session_factory=lambda *a: None)
    assert e.value.code == 2
    cap = capsys.readouterr()
    assert cap.err.startswith(
        "error: BBWARDEN_URL must not contain a query string or fragment"
    )
    assert SECRET not in cap.err + cap.out


@pytest.mark.parametrize(
    "url",
    [
        f"https://crowd.example.com/crowd?x={SECRET}",
        f"https://crowd.example.com/#{SECRET}",
    ],
)
def test_crowd_url_query_or_fragment_refused(url):
    env = {"CROWD_URL": url, "CROWD_APP": "a", "CROWD_APP_PASSWORD": "p"}
    with pytest.raises(core.BBWardenError) as e:
        live.crowd_from_env(env, session_factory=lambda: None)
    assert "CROWD_URL must not contain a query string or fragment" in str(e.value)
    assert SECRET not in str(e.value)


class TypeErrBackend(Backend):
    def remove_user(self, ws, scope, key, user):
        raise TypeError(f"bad arg {SECRET}")

    def remove_global(self, user):
        raise TypeError(f"bad arg {SECRET}")


def test_partial_apply_unexpected_error_shows_type_only(monkeypatch, capsys, caplog):
    caplog.set_level(logging.DEBUG, logger="bbwarden")
    run(monkeypatch, TypeErrBackend())
    with pytest.raises(SystemExit) as e:
        cli.main(["offboard", "root", "--apply"])
    assert str(e.value.code) == "error: TypeError"
    err = capsys.readouterr().err
    assert "APPLY STOPPED" in err and SECRET not in err and SECRET not in caplog.text


def test_global_step_unexpected_error_shows_type_only(caplog):
    caplog.set_level(logging.DEBUG, logger="bbwarden")
    ws = ws_root()
    plan = [s for s in core.offboard(ws, "root") if s["scope"] == "global"]
    with pytest.raises(core.PartialApply) as e:
        core.apply_offboard(ws, "root", plan, TypeErrBackend())
    assert str(e.value) == "TypeError" and SECRET not in caplog.text


def test_bbwarden_error_message_still_shown(monkeypatch):
    run(monkeypatch, Backend(fail_regular=True))
    with pytest.raises(SystemExit) as e:
        cli.main(["offboard", "root", "--apply"])
    assert "HTTP 500 on DELETE" in str(e.value.code)


@pytest.mark.parametrize("url", ["https://[::1", "https://bb.example.com:99999"])
def test_invalid_url_is_config_error(url, capsys):
    env = {"BBWARDEN_URL": url, "BBWARDEN_USER": "u", "BBWARDEN_TOKEN": "t"}
    with pytest.raises(SystemExit) as e:
        cli.main(["direct"], env=env, session_factory=lambda *a: None)
    assert e.value.code == 2
    assert capsys.readouterr().err.startswith("error: BBWARDEN_URL is not a valid URL")


def test_readme_exit_code_2_row_lists_url_refusals():
    from pathlib import Path

    row = next(
        ln
        for ln in Path(__file__)
        .parent.parent.joinpath("README.md")
        .read_text()
        .splitlines()
        if ln.startswith("| 2 |")
    )
    for phrase in (
        "not a valid URL",
        "no hostname",
        "credentials",
        "query string or a fragment",
    ):
        assert phrase in row
