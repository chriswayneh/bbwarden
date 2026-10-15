import argparse
import csv
import logging
import os
import sys
import unicodedata

from . import __version__, core
from .http import BBWardenError, ConfigError
from .live import backend_from_env, crowd_from_env, crowd_status
from .model import demo_workspace

# Displayed and exported columns per command. Plan rows may carry extra internal fields
# (regroup keeps the raw user "key" for --apply); they are shown only if listed here.
COLUMNS = {
    "who": ["repo", "user", "effective", "sources", "flag"],
    "direct": ["scope", "name", "user", "permission"],
    "orphans": ["repo", "user", "access", "idp_status"],
    "regroup": ["repo", "user", "action", "group", "detail"],
    "offboard": ["scope", "name", "action", "detail"],
}
FORMULA = ("=", "+", "-", "@", "\t", "\r")


def _is_control(c):
    """C0, DEL, C1, and Unicode Cc (control), Cf (format, incl. bidi overrides and zero-width
    characters) and Cs (lone surrogates)."""
    o = ord(c)
    return (
        o < 0x20 or 0x7F <= o <= 0x9F or unicodedata.category(c) in ("Cc", "Cf", "Cs")
    )


def escape(s):
    """Text safe for a terminal: every control or format character becomes its escaped code
    point (\\x1b, \\u202e, \\U000e0001), so names from Bitbucket or an IdP cannot move the
    cursor, set the title, clear the screen or reorder text. Used for every table cell and
    every stderr line built from data."""
    out = []
    for c in str(s):
        if not _is_control(c):
            out.append(c)
        elif ord(c) <= 0xFF:
            out.append(f"\\x{ord(c):02x}")
        elif ord(c) <= 0xFFFF:
            out.append(f"\\u{ord(c):04x}")
        else:
            out.append(f"\\U{ord(c):08x}")
    return "".join(out)


def _escape_lines(s):
    """escape() per line, keeping the line breaks of multi-line messages."""
    return "\n".join(escape(ln) for ln in str(s).split("\n"))


class EscapingFormatter(logging.Formatter):
    """Log lines go to stderr too, and step labels carry names from the server."""

    def format(self, record):
        return _escape_lines(super().format(record))


def _safe_cell(v):
    """Neutralize spreadsheet formulas (CSV injection) by prefixing a single quote, also when
    the formula follows leading whitespace or invisible control and format characters (for
    example \\u200b or \\x1b). The data itself is kept as is."""
    v = str(v)
    lead = v
    while lead and (lead[0].isspace() or _is_control(lead[0])):
        lead = lead[1:]
    return "'" + v if v.startswith(FORMULA) or lead.startswith(FORMULA[:4]) else v


def table(rows, cols):
    if not rows:
        return "(no results)"
    rows = [{c: escape(r.get(c, "")) for c in cols} for r in rows]
    w = {c: max(len(c), *(len(r[c]) for r in rows)) for c in cols}
    line = lambda r: "  ".join(str(r[c]).ljust(w[c]) for c in cols).rstrip()
    return "\n".join(
        [line({c: c.upper() for c in cols}), "  ".join("-" * w[c] for c in cols)]
        + [line(r) for r in rows]
    )


def write_csv(rows, path, cols):
    """Always writes the header, even with no rows."""
    with open(path, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        wr.writeheader()
        wr.writerows({c: _safe_cell(r.get(c, "")) for c in cols} for r in rows)


def get_ws(args, env=None, **kw):
    if args.demo:
        return demo_workspace(), None
    backend = backend_from_env(env, insecure=getattr(args, "insecure", False), **kw)
    return backend.load(), backend


def build_parser():
    p = argparse.ArgumentParser(
        prog="bbwarden", description="Bitbucket least-privilege and offboarding"
    )
    p.add_argument("--version", action="version", version=f"bbwarden {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--demo", action="store_true", help="use built-in mock workspace"
    )
    common.add_argument("--csv", metavar="OUT", help="also write results to CSV")
    common.add_argument(
        "--insecure",
        action="store_true",
        help="allow http:// for BBWARDEN_URL and CROWD_URL (local test servers only)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("who", parents=[common], help="effective access per person")
    s.add_argument("target", help="repo slug or project key")
    sub.add_parser(
        "direct", parents=[common], help="direct user grants that skip groups"
    )
    s = sub.add_parser(
        "orphans", parents=[common], help="access held by disabled identities"
    )
    s.add_argument("--idp", choices=["crowd", "csv"], required=True)
    s.add_argument("--idp-file", help="IdP CSV export (user,active) for --idp csv")
    s = sub.add_parser(
        "regroup", parents=[common], help="replace direct grants with group grants"
    )
    s.add_argument("repo")
    s.add_argument("--apply", action="store_true")
    s = sub.add_parser("offboard", parents=[common], help="remove a user everywhere")
    s.add_argument("user", help="username (Data Center) or account_id/nickname (Cloud)")
    s.add_argument("--apply", action="store_true")
    s.add_argument(
        "--skip-memberships",
        action="store_true",
        help="only remove direct grants; leave group memberships to your directory",
    )
    return p


EXIT_OK, EXIT_ERROR, EXIT_CONFIG = 0, 1, 2  # 2 also covers argparse usage errors


def main(argv=None, env=None, **kw):
    args = build_parser().parse_args(argv)
    if not logging.getLogger("bbwarden").handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(EscapingFormatter("bbwarden: %(levelname)s %(message)s"))
        logging.basicConfig(level=logging.WARNING, handlers=[handler])
    try:
        return _run(args, env, **kw)
    except ConfigError as e:
        print(f"error: {escape(e)}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    except core.PartialApply as e:
        total = len(e.done) + 1 + len(e.pending)
        print(
            f"\nAPPLY STOPPED: {len(e.done)} of {total} steps finished before a failure.",
            file=sys.stderr,
        )
        for d in e.done:
            print(f"  done    {escape(d)}", file=sys.stderr)
        print(f"  FAILED  {escape(e.failed)}", file=sys.stderr)
        for p in e.pending:
            print(f"  not run {escape(p)}", file=sys.stderr)
        print(
            "Re-run the same command (without --apply first) to see what is left.",
            file=sys.stderr,
        )
        sys.exit(f"error: {escape(core.describe_error(e.error))}")
    except (BBWardenError, core.BadIdpFile) as e:
        sys.exit(f"error: {escape(e)}")
    except OSError as e:
        if e.filename:
            sys.exit(
                f"error: cannot open {escape(e.filename)}: {escape(e.strerror or e)}"
            )
        sys.exit(f"error: {escape(e.strerror or e)}")


def _check_writable(path):
    """Fail before any output if the CSV path cannot be written. Leaves no new file behind."""
    existed = os.path.exists(path)
    with open(path, "a", newline=""):
        pass
    if not existed:
        os.remove(path)


def _run(args, env, **kw):
    if args.csv:
        _check_writable(args.csv)
    ws, backend = get_ws(
        args, env, **{k: v for k, v in kw.items() if k != "crowd_session"}
    )
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
                    raise ConfigError("--idp csv needs --idp-file")
                status = core.load_idp_csv(args.idp_file)
            elif args.demo:
                status = {u: v["active"] for u, v in ws.users.items()}
            else:
                http_kw = {
                    k: v
                    for k, v in kw.items()
                    if k not in ("session_factory", "crowd_session")
                }
                crowd = crowd_from_env(
                    env,
                    session_factory=kw.get("crowd_session"),
                    insecure=args.insecure,
                    **http_kw,
                )
                status = crowd_status(
                    crowd, sorted({v.get("name") or u for u, v in ws.users.items()})
                )
            rows = core.orphans(ws, status)
        elif args.cmd == "regroup":
            rows = core.regroup(ws, args.repo)
            if args.apply:
                core.apply_regroup(ws, rows, backend)
                note = f"APPLIED to {target}"
            else:
                note = "DRY RUN: re-run with --apply to make these changes"
        elif args.cmd == "offboard":
            if backend and not args.skip_memberships:
                backend.load_memberships(ws, args.user)
            user = core.resolve_user(ws, args.user)
            rows = core.offboard(ws, user, memberships=not args.skip_memberships)
            if args.apply:
                core.apply_offboard(ws, user, rows, backend)
                note = f"APPLIED to {target}"
            else:
                note = "DRY RUN: re-run with --apply to make these changes"
    except KeyError as e:
        sys.exit(f"error: {escape(e.args[0])}")
    cols = COLUMNS[args.cmd]
    print(table(rows, cols))
    if ws.manual:
        total = len(rows)
        print(
            f"\nAPPLY INCOMPLETE: {total - len(ws.manual)} of {total} steps finished. "
            "MANUAL steps left:",
            file=sys.stderr,
        )
        for lab, why in ws.manual:
            print(f"  MANUAL  {escape(lab)}: {escape(why)}", file=sys.stderr)
        note = ""
    if note:
        print(f"\n{note}")
    for n in ws.notes:
        print(f"NOTE: {escape(n)}", file=sys.stderr)
    if args.csv:
        write_csv(rows, args.csv, cols)
    return 1 if ws.manual else 0


if __name__ == "__main__":
    sys.exit(main())
