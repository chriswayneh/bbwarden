import argparse
import csv
import os
import sys

from . import core
from .model import demo_workspace, load_live


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


def get_ws(args):
    if args.demo:
        return demo_workspace()
    url = os.environ.get("BBWARDEN_URL")
    if not url:
        sys.exit("error: set BBWARDEN_URL, BBWARDEN_USER, BBWARDEN_TOKEN or use --demo")
    return load_live(url, os.environ.get("BBWARDEN_USER"), os.environ.get("BBWARDEN_TOKEN"),
                     cloud="bitbucket.org" in url)


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


def main(argv=None):
    args = build_parser().parse_args(argv)
    ws = get_ws(args)
    note = ""
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
                sys.exit("error: live Crowd lookup lands in milestone 2; use --demo or --idp csv")
            rows = core.orphans(ws, status)
        elif args.cmd == "regroup":
            rows = core.regroup(ws, args.repo)
            if args.apply:
                if not args.demo:
                    sys.exit("error: live --apply lands in milestone 2")
                core.apply_regroup(ws, rows)
                note = "APPLIED to demo workspace"
            else:
                note = "DRY RUN: re-run with --apply to make these changes"
        elif args.cmd == "offboard":
            rows = core.offboard(ws, args.user)
            if args.apply:
                if not args.demo:
                    sys.exit("error: live --apply lands in milestone 2")
                core.apply_offboard(ws, args.user, rows)
                note = "APPLIED to demo workspace"
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
