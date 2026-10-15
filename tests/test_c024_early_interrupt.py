"""Codex runner-2026-10-15 on dfd0b68: Known limit: early Ctrl-C."""

import sys

import pytest

from bbwarden import cli

# Known limit 2: Ctrl-C before main()'s error handling


def test_l2_ctrl_c_during_argument_parsing(monkeypatch, capsys):
    def stop():
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "build_parser", stop)
    with pytest.raises(SystemExit) as e:
        cli.main(["direct", "--demo"])
    assert e.value.code == 130
    assert capsys.readouterr().err.strip() == "interrupted"


def test_l2_entry_point_handles_ctrl_c_during_import(monkeypatch, capsys):
    import importlib

    entry = importlib.import_module("bbwarden._entry")

    class Stop:
        def find_spec(self, name, path=None, target=None):
            if name == "bbwarden.cli":
                raise KeyboardInterrupt

    monkeypatch.delitem(sys.modules, "bbwarden.cli", raising=False)
    monkeypatch.setattr(sys, "meta_path", [Stop()] + sys.meta_path)
    with pytest.raises(SystemExit) as e:
        entry.run()
    assert e.value.code == 130
    assert capsys.readouterr().err.strip() == "interrupted"


def test_l2_console_script_uses_entry():
    from pathlib import Path

    text = (Path(__file__).parent.parent / "pyproject.toml").read_text()
    assert 'bbwarden = "bbwarden._entry:run"' in text
