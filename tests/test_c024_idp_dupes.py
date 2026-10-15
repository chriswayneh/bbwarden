"""Codex runner-2026-10-15 on dfd0b68: 6. duplicate IdP CSV columns."""

import pytest

from bbwarden import cli

# 6. duplicate IdP CSV columns


@pytest.mark.parametrize(
    "header", ["user,active,active", "user,active, active ", "user,user,active"]
)
def test_f6_duplicate_idp_columns_rejected(tmp_path, header, capsys):
    f = tmp_path / "idp.csv"
    f.write_text(f"{header}\ndave,false,true\n", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        cli.main(["orphans", "--demo", "--idp", "csv", "--idp-file", str(f)])
    assert e.value.code not in (0, None)
    assert "duplicate column" in str(e.value.code)
