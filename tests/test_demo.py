import csv

from bbwarden import core
from bbwarden.cli import main
from bbwarden.model import demo_workspace


def test_who_sources():
    rows = {(r["repo"], r["user"]): r for r in core.who(demo_workspace(), "api")}
    assert rows[("api", "bob")]["effective"] == "ADMIN"
    assert "direct" in rows[("api", "bob")]["sources"]
    assert rows[("api", "dave")]["flag"] == "DISABLED"


def test_who_project_and_unknown(capsys):
    assert {r["repo"] for r in core.who(demo_workspace(), "CORE")} == {"api", "web"}
    try:
        main(["who", "nope", "--demo"])
        assert False
    except SystemExit as e:
        assert "unknown" in str(e)


def test_direct():
    rows = core.direct(demo_workspace())
    assert len(rows) == 5
    assert {"scope": "project", "name": "CORE", "user": "dave", "permission": "WRITE"} in rows


def test_orphans_crowd_demo(capsys):
    main(["orphans", "--idp", "crowd", "--demo"])
    out = capsys.readouterr().out
    assert "dave" in out and "frank" in out and "erin" not in out


def test_orphans_csv(tmp_path):
    f = tmp_path / "idp.csv"
    f.write_text("user,active\nerin,false\nalice,true\n")
    rows = core.orphans(demo_workspace(), core.load_idp_csv(f))
    assert {r["user"] for r in rows if r["idp_status"] == "disabled"} == {"erin"}


def test_regroup_dry_and_apply(capsys):
    ws = demo_workspace()
    plan = core.regroup(ws, "api")
    assert {p["user"]: p["action"] for p in plan} == {"bob": "replace", "erin": "manual"}
    main(["regroup", "api", "--demo"])
    assert "DRY RUN" in capsys.readouterr().out
    core.apply_regroup(ws, plan)
    assert "bob" not in ws.repos["api"]["users"]
    assert ws.repos["api"]["groups"]["devs"] == "ADMIN"


def test_offboard(capsys):
    ws = demo_workspace()
    plan = core.offboard(ws, "alice")
    assert {(p["scope"], p["name"]) for p in plan} == {("group", "admins"), ("group", "devs")}
    core.apply_offboard(ws, "alice", plan)
    assert all("alice" not in m for m in ws.groups.values())
    main(["offboard", "dave", "--demo", "--apply"])
    assert "APPLIED" in capsys.readouterr().out


def test_csv_out(tmp_path):
    out = tmp_path / "o.csv"
    main(["direct", "--demo", "--csv", str(out)])
    with open(out, newline="") as f:
        assert len(list(csv.DictReader(f))) == 5
