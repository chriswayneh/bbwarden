import argparse
import csv
import sys

from . import core
from .http import BBWardenError
from .live import backend_from_env, crowd_from_env, crowd_status
from .model import demo_workspace


def table(rows):
    if not rows:
        return "(no results)"
    cols = list(rows[0])
    w = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    line = lambda r: "  ".join(str(r[c]).ljust(w[c]) for c in cols).rstrip()
    return "\n".join([line({c: c.upper() for c in cols}),
                      "  ".join("-" * w[c] for c in cols)] + [line(r) for r in rows])


def write_csv(rows, path):
    with open(path, "w", newline="") as f:
        if rows:
            wr = csv.DictWriter(f, fieldnames=list(rows[0]))
            wr.writeheader()
            wr.writerows(rows)


def get_ws(args, env=None, **kw):
    if args.demo:
        return demo_workspace(), None
    backend = backend_from_env(env, **kw)
    return backend.load(), backend


def build_parser():
    p = argparse.ArgumentParser(prog="bbwarden", description="Bitbucket least-privilege and offboarding")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--demo", action="store_true", help="use built-in mock workspace")
    common.add_argument("--csv", metavar="OUT", help="also write results to CSV")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("who", parents=[common], help="effective access per person")
    s.add_argument("target", help="repo slug or project key")
    sub.add_parser("direct", parents=[common], help="direct user grants that skip groups")
    s = sub.add_parser("orphans", parents=[common], help="access held by disabled identities")
    s.add_argument("--idp", choices=["crowd", "csv"], required=True)
    s.add_argument("--idp-file", help="IdP CSV export (user,active) for --idp csv")
    s = sub.add_parser("regroup", parents=[common], help="replace direct grants with group grants")
    s.add_argument("repo")
    s.add_argument("--apply", action="store_true")
    s = sub.add_parser("offboard", parents=[common], help="remove a user everywhere")
    s.add_argument("user")
    s.add_argument("--apply", action="store_true")
    return p


def main(argv=None, env=None, **kw):
    args = build_parser().parse_args(argv)
    try:
        return _run(args, env, **kw)
    except BBWardenError as e:
        sys.exit(f"error: {e}")


def _run(args, env, **kw):
    ws, backend = get_ws(args, env, **{k: v for k, v in kw.items() if k != "crowd_session"})
    note = ""
    target = "demo workspace" if args.demo else "Bitbucket"
    try:
        if args.cmd == "who":
            rows = core.who(ws, args.target)
        elif args.cmd == "direct":
            rows = core.direct(ws)
        elif args.cmd == "orphans":
            if args.idp == "csv":
                if not args.idp_file:
                    sys.exit("error: --idp csv needs --idp-file")
                status = core.load_idp_csv(args.idp_file)
            elif args.demo:
                status = {u: v["active"] for u, v in ws.users.items()}
            else:
                http_kw = {k: v for k, v in kw.items() if k not in ("session_factory", "crowd_session")}
                crowd = crowd_from_env(env, session_factory=kw.get("crowd_session"), **http_kw)
                status = crowd_status(crowd, sorted(ws.users))
            rows = core.orphans(ws, status)
        elif args.cmd == "regroup":
            rows = core.regroup(ws, args.repo)
            if args.apply:
                core.apply_regroup(ws, rows, backend)
                note = f"APPLIED to {target}"
            else:
                note = "DRY RUN: re-run with --apply to make these changes"
        elif args.cmd == "offboard":
            rows = core.offboard(ws, args.user)
            if args.apply:
                core.apply_offboard(ws, args.user, rows, backend)
                note = f"APPLIED to {target}"
            else:
                note = "DRY RUN: re-run with --apply to make these changes"
    except KeyError as e:
        sys.exit(f"error: {e.args[0]}")
    print(table(rows))
    if note:
        print(f"\n{note}")
    if args.csv:
        write_csv(rows, args.csv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
