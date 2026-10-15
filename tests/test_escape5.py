"""QE on 91c4f55: CSV escaping by default, --raw-csv opt-in, surrogates, IdP file encoding,
last-resort error handler, consistent log escaping."""

import csv
import logging

import pytest
from test_round8 import Backend, run, ws_root

from bbwarden import cli
from bbwarden.model import demo_workspace

NASTY = "a\x1b[31m\x1b]8;;http://evil\x07link\x1b]8;;\x07\u202e\u2028\u2029\x9bZ"
RAW_CTRL = ("\x1b", "\x07", "\u202e", "\u2028", "\u2029", "\x9b")


def ws_with(name):
    ws = demo_workspace()
    ws.repos["api"]["users"][name] = "WRITE"
    return ws


def cells(path):
    with open(path, encoding="utf-8", newline="") as f:
        return [c for row in csv.reader(f) for c in row]


def run_ws(monkeypatch, ws):
    monkeypatch.setattr("bbwarden.cli.get_ws", lambda args, env=None, **kw: (ws, None))


def test_lone_surrogate_csv_does_not_crash(monkeypatch, tmp_path, capsys):
    run_ws(monkeypatch, ws_with("bad\ud800name"))
    out = tmp_path / "o.csv"
    assert cli.main(["who", "api", "--csv", str(out)]) == 0
    assert "bad\\ud800name" in cells(out)


def test_lone_surrogate_raw_csv_does_not_crash(monkeypatch, tmp_path, capsys):
    run_ws(monkeypatch, ws_with("bad\ud800name"))
    out = tmp_path / "o.csv"
    assert cli.main(["who", "api", "--csv", str(out), "--raw-csv"]) == 0
    assert "bad\ufffdname" in cells(
        out
    )  # U+FFFD since 0.2.4, see test_c024_raw_surrogate


def test_csv_escaped_by_default(monkeypatch, tmp_path, capsys):
    run_ws(monkeypatch, ws_with(NASTY))
    out = tmp_path / "o.csv"
    cli.main(["who", "api", "--csv", str(out)])
    text = out.read_text(encoding="utf-8")
    assert not any(c in text for c in RAW_CTRL)
    assert "a\\x1b[31m\\x1b]8;;http://evil\\x07link" in text
    assert "--raw-csv" not in capsys.readouterr().err


def test_csv_default_still_formula_guarded(tmp_path):
    p = tmp_path / "o.csv"
    cli.write_csv([{"user": "=cmd()"}, {"user": "\u200b=cmd()"}], p, ["user"])
    c = cells(p)
    assert c[1] == "'=cmd()" and c[2] in ("\\u200b=cmd()", "'\\u200b=cmd()")
    assert not c[2].startswith(("=", "+", "-", "@"))


def test_raw_csv_keeps_data_guarded_and_warns(monkeypatch, tmp_path, capsys):
    run_ws(monkeypatch, ws_with("\u202e=evil"))
    out = tmp_path / "o.csv"
    cli.main(["who", "api", "--csv", str(out), "--raw-csv"])
    assert "'\u202e=evil" in cells(out)
    err = capsys.readouterr().err
    assert "WARNING: --raw-csv" in err


def test_raw_csv_flag_on_every_command():
    p = cli.build_parser()
    for cmd in (
        ["who", "x"],
        ["direct"],
        ["orphans", "--idp", "crowd"],
        ["regroup", "x"],
        ["offboard", "x"],
    ):
        assert p.parse_args(cmd + ["--raw-csv"]).raw_csv is True


def test_idp_file_not_utf8_exit_2(tmp_path, capsys):
    f = tmp_path / "idp.csv"
    f.write_bytes(b"user,active\n\xffdave\x1b,false\n")
    with pytest.raises(SystemExit) as e:
        cli.main(["orphans", "--demo", "--idp", "csv", "--idp-file", str(f)])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ") and "UTF-8" in err and "Traceback" not in err
    assert "\x1b" not in err


def test_idp_file_with_bom_ok(tmp_path, capsys):
    f = tmp_path / "idp.csv"
    f.write_bytes(b"\xef\xbb\xbfuser,active\ndave,false\n")
    assert cli.main(["orphans", "--demo", "--idp", "csv", "--idp-file", str(f)]) == 0


def test_last_resort_handler(monkeypatch, capsys):
    def boom(*a, **k):
        raise TypeError("bad\nbbwarden: ERROR forged\x1b[2J")

    monkeypatch.setattr(cli, "_run", boom)
    with pytest.raises(SystemExit) as e:
        cli.main(["direct", "--demo"])
    assert e.value.code == 1
    err = capsys.readouterr().err
    lines = err.splitlines()
    assert lines[0].startswith("error: unexpected ")
    assert lines[-1] == "TypeError" and "TypeError: bad" not in err  # type only
    assert "\x1b" not in err
    assert not any(ln.startswith("bbwarden: ERROR forged") for ln in lines)


def test_log_and_failed_lines_not_double_escaped(monkeypatch, capsys, caplog):
    caplog.set_level(logging.ERROR, logger="bbwarden")
    ws = ws_root()
    run(monkeypatch, Backend(fail_regular=True), ws)
    with pytest.raises(SystemExit):
        cli.main(["offboard", "root", "--apply"])
    msgs = [r.getMessage() for r in caplog.records]
    assert any(
        m.startswith("apply failed at step remove direct grant") for m in msgs
    ), msgs
    assert not any("'remove" in m for m in msgs)
