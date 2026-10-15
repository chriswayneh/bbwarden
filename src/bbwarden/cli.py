import argparse
import builtins
import copy
import csv
import errno
import io
import logging
import os
import secrets
import stat
import sys
import traceback
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


# Cc control, Cf format (bidi overrides, zero-width), Cs lone surrogates, Co private use,
# Cn unassigned, Zl/Zp line and paragraph separators (U+2028, U+2029).
_UNSAFE = ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp")


def _is_control(c):
    """C0, DEL, C1, and the Unicode categories in _UNSAFE."""
    o = ord(c)
    return o < 0x20 or 0x7F <= o <= 0x9F or unicodedata.category(c) in _UNSAFE


def escape(s):
    """Text safe for a terminal: every control or format character becomes its escaped code
    point (\\x1b, \\u202e, \\U000e0001), so names from Bitbucket or an IdP cannot move the
    cursor, set the title, clear the screen or reorder text. Used for every table cell and
    every stderr line built from data."""
    out = []
    for c in str(s):
        if c == "\\":  # so a literal "\\x1b" in a name cannot pass for an escaped ESC
            out.append("\\\\")
        elif not _is_control(c):
            out.append(c)
        elif ord(c) <= 0xFF:
            out.append(f"\\x{ord(c):02x}")
        elif ord(c) <= 0xFFFF:
            out.append(f"\\u{ord(c):04x}")
        else:
            out.append(f"\\U{ord(c):08x}")
    return "".join(out)


class EscapingFormatter(logging.Formatter):
    """Log lines go to stderr too, and step labels carry names from the server. The message
    with its arguments is escaped before formatting, so a name holding a newline cannot start
    a forged log line; only the formatter's own line breaks (tracebacks) remain."""

    def __init__(self, *args, safe=True, **kwargs):
        """safe=True (the default) shows exception types only in tracebacks, as SECURITY.md
        promises: messages of unexpected exceptions could carry tokens or URLs."""
        super().__init__(*args, **kwargs)
        self.safe = safe

    def format(self, record):
        record = copy.copy(record)
        record.msg, record.args = escape(record.getMessage()), None
        record.exc_text = None  # never reuse text cached by another formatter
        return super().format(record)

    def formatException(self, ei):
        """Rendered by _exc_lines, not traceback.format_exception: frame, source and chain
        separator lines stay real lines (each escaped), while the exception text with its
        notes is escaped as one unit, so a newline in a message or note shows as \\x0a and
        cannot start a forged log line. Same output on Python 3.9 to 3.13."""
        etype, exc = ei[0], ei[1]
        if exc is None:  # never instantiate the type: its __init__ may need arguments
            return escape(getattr(etype, "__name__", "Exception"))
        try:
            return "\n".join(_exc_lines(exc, safe=self.safe))
        except (Exception, RecursionError):  # noqa: BLE001 - logging must never raise
            return escape(f"{type(exc).__name__}: <traceback unavailable>")

    def formatStack(self, stack_info):
        return "\n".join(escape(ln) for ln in stack_info.split("\n"))


_CAUSE = "The above exception was the direct cause of the following exception:"
_CONTEXT = "During handling of the above exception, another exception occurred:"


MAX_EXC_SHOWN = (
    50  # chained exceptions, ExceptionGroup nesting levels and members shown
)


def _safe_str(x, fallback):
    try:
        return str(x)
    except Exception:  # noqa: BLE001 - a broken __str__ must not break logging
        return fallback


def _exc_text(exc, safe=False):
    """'module.Type: message' plus any __notes__ (3.11+), as one escaped line. safe=True
    applies describe_error: our own BBWardenError keeps its message (written to be safe to
    show), anything else shows its type only, without message or notes."""
    t = type(exc)
    name = (
        t.__qualname__
        if t.__module__ == "builtins"
        else f"{t.__module__}.{t.__qualname__}"
    )
    if safe and not isinstance(exc, BBWardenError):
        return escape(name)
    msg = _safe_str(exc, "<exception str() failed>")
    text = (
        f"{name}: {msg}" if msg else name
    )  # ExceptionGroup str() has "(N sub-exceptions)"
    notes = getattr(exc, "__notes__", None)
    if isinstance(notes, (list, tuple)):
        text = "\n".join([text] + [_safe_str(n, "<note str() failed>") for n in notes])
    return escape(text)


def _next_in_chain(exc):
    """(older exception, separator) or (None, None), like the standard traceback."""
    if exc.__cause__ is not None:
        return exc.__cause__, _CAUSE
    if exc.__context__ is not None and not exc.__suppress_context__:
        return exc.__context__, _CONTEXT
    return None, None


def _exc_lines(root, safe=False):
    """Traceback lines for root, its chain (oldest first) and ExceptionGroup members.
    Iterative with an explicit stack, so no exception shape can hit the recursion limit;
    chains and group nesting are cut at MAX_EXC_SHOWN with a "... more" line."""
    group_type = getattr(builtins, "BaseExceptionGroup", None)
    seen: set = set()
    out: list = []
    # Work items: ("line", text, prefix, depth) or ("exc", exception, prefix, depth).
    stack: list = [("exc", root, "", 0)]
    while stack:
        kind, item, prefix, depth = stack.pop()
        if kind == "line":
            out.append(prefix + item)
            continue
        chain: list = []
        seps: list = []
        exc = item
        while exc is not None and id(exc) not in seen and len(chain) < MAX_EXC_SHOWN:
            seen.add(id(exc))
            chain.append(exc)
            exc, sep = _next_in_chain(exc)
            seps.append(sep)
        more = 0
        while exc is not None and id(exc) not in seen:  # count only, never render
            seen.add(id(exc))
            more += 1
            exc, _ = _next_in_chain(exc)
        seq: list = []
        if more:
            seq += [("line", f"... ({more} more chained exceptions)", prefix, depth)]
            seq += [("line", "", prefix, depth)]
        for k in range(len(chain) - 1, -1, -1):  # oldest first
            e = chain[k]
            if e.__traceback__ is not None:
                seq.append(
                    ("line", "Traceback (most recent call last):", prefix, depth)
                )
                for frame in traceback.format_tb(e.__traceback__):
                    seq += [
                        ("line", escape(ln), prefix, depth)
                        for ln in frame.rstrip("\n").split("\n")
                    ]
            seq.append(("line", _exc_text(e, safe), prefix, depth))
            if group_type is not None and isinstance(e, group_type):
                subs = list(e.exceptions)
                if depth + 1 >= MAX_EXC_SHOWN:
                    msg = f"... ({len(subs)} sub-exceptions not shown: nested too deep)"
                    seq.append(("line", msg, prefix, depth))
                else:
                    for n, sub in enumerate(subs[:MAX_EXC_SHOWN], 1):
                        head = f"+---------------- sub-exception {n} of {len(subs)} ----------------"
                        seq.append(("line", head, prefix, depth))
                        seq.append(("exc", sub, prefix + "| ", depth + 1))
                    if len(subs) > MAX_EXC_SHOWN:
                        rest = len(subs) - MAX_EXC_SHOWN
                        seq.append(
                            ("line", f"... ({rest} more sub-exceptions)", prefix, depth)
                        )
                    seq.append(("line", "+" + "-" * 54, prefix, depth))
            if k > 0:  # separator between this exception and the newer one
                sep = seps[k - 1]
                seq += [("line", t, prefix, depth) for t in ("", sep, "")]
        stack.extend(reversed(seq))
    return out


def display_width(s):
    """Terminal columns: East Asian wide and fullwidth count 2; combining, nonspacing (Mn,
    including variation selectors such as U+FE0F) and enclosing (Me) marks count 0."""
    return sum(
        0
        if unicodedata.combining(c) or unicodedata.category(c) in ("Mn", "Me")
        else 2
        if unicodedata.east_asian_width(c) in ("W", "F")
        else 1
        for c in s
    )


class Parser(argparse.ArgumentParser):
    """argparse echoes bad arguments; escape them like every other stderr line."""

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: {escape(message)}\n")


def _no_surrogates(v):
    """Lone surrogates (Cs) cannot be encoded as UTF-8. Raw CSV writes U+FFFD for them,
    the standard replacement character, so they never look like the literal text
    \\ud800 that a name could really contain."""
    return "".join("\ufffd" if unicodedata.category(c) == "Cs" else c for c in v)


def _safe_cell(v, raw=False):
    """One CSV cell. By default escaped like terminal output (escape()), so a CSV opened in
    a terminal or viewer never carries raw control, bidi or separator characters. With
    raw=True the data is kept except lone surrogates. Either way spreadsheet formulas are
    neutralized with a leading single quote, also behind leading whitespace or invisible
    control and format characters (for example \\u200b or \\x1b)."""
    v = str(v)
    lead = v
    while lead and (lead[0].isspace() or _is_control(lead[0])):
        lead = lead[1:]
    guard = v.startswith(FORMULA) or lead.startswith(FORMULA[:4])
    v = _no_surrogates(v) if raw else escape(v)
    return "'" + v if guard or v.startswith(FORMULA) else v


def table(rows, cols):
    if not rows:
        return "(no results)"
    rows = [{c: escape(r.get(c, "")) for c in cols} for r in rows]
    w = {c: max(len(c), *(display_width(r[c]) for r in rows)) for c in cols}
    line = lambda r: "  ".join(
        r[c] + " " * (w[c] - display_width(r[c])) for c in cols
    ).rstrip()
    return "\n".join(
        [line({c: c.upper() for c in cols}), "  ".join("-" * w[c] for c in cols)]
        + [line(r) for r in rows]
    )


def write_csv(rows, path, cols, raw=False):
    """Returns the stdout state ("ok", "pipe" or "error", see stdout_call). UTF-8, always with the header row, even with no rows. See _safe_cell for raw.
    Written to a temporary sibling and renamed over the target, so a failed write
    never leaves a truncated file and never destroys the previous one. A symlink is
    followed, so its target is updated and the link stays a link. The temporary file is
    owner-only (0o600) while rows are written and gets its final mode just before the
    rename: the existing file's mode, or 0o666 minus the umask for a new file.
    An existing target that is not a regular file (a FIFO, /dev/stdout, /dev/fd/N, a
    character device) is written directly: it cannot be replaced by a rename."""
    if _is_stdout(path):  # `--csv out.csv > out.csv`: append after the table, no rename
        return _write_to_stdout(rows, cols, raw)
    _refuse_socket(path)
    if _is_special(path):
        state = flush_stdout()  # keep the table before the CSV (/dev/tty and the like)
        with open(path, "w", newline="", encoding="utf-8") as f:
            _write_rows(f, rows, cols, raw)
        return state
    real = os.path.realpath(path)
    if os.path.isdir(real):
        raise IsADirectoryError(21, "Is a directory", path)
    try:
        mode = stat.S_IMODE(os.stat(real).st_mode)
    except FileNotFoundError:
        mode = _new_file_mode(real, path)
    fd, tmp = _temp_sibling(real, path, 0o600)
    try:
        f = os.fdopen(fd, "w", newline="", encoding="utf-8")
    except BaseException:
        os.close(fd)
        _remove_quietly(tmp)
        raise
    try:
        with f:
            _write_rows(f, rows, cols, raw)
        os.chmod(tmp, mode)
        os.replace(tmp, real)
    except BaseException:
        _remove_quietly(tmp)
        raise
    return "ok"


def _write_rows(f, rows, cols, raw):
    wr = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
    wr.writeheader()
    wr.writerows({c: _safe_cell(r.get(c, ""), raw) for c in cols} for r in rows)


def _is_special(path):
    """True for an existing target (symlinks followed) that is neither a regular file nor
    a directory, for example a FIFO or a character device."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    return not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode))


def _write_to_stdout(rows, cols, raw):
    """CSV through stdout, still UTF-8 with \r\n rows whatever the console encoding:
    built in memory and written as UTF-8 bytes to stdout's byte buffer (text if there
    is no buffer). No wrapper is put around the buffer, so nothing can close it. Goes
    through stdout_call; returns its "ok", "pipe" or "error"."""
    text = io.StringIO(newline="")
    _write_rows(text, rows, cols, raw)

    def write(out):
        out.flush()  # the table goes first
        buf = getattr(out, "buffer", None)
        if buf is None:
            out.write(text.getvalue())
            out.flush()
        else:
            buf.write(text.getvalue().encode("utf-8"))
            buf.flush()

    return stdout_call(write)


def _is_stdout(path):
    """True when path is the very file stdout points at (same device and inode), for
    example `--csv out.csv > out.csv`. A stdout without a real file descriptor (pytest
    capture, an io.StringIO) never matches."""
    try:
        out = os.fstat(sys.stdout.fileno())
        st = os.stat(path)
    # io.UnsupportedOperation is an OSError
    except (AttributeError, OSError, ValueError):
        return False
    return (st.st_dev, st.st_ino) == (out.st_dev, out.st_ino)


def _refuse_socket(path):
    """A Unix socket cannot be opened as a file; say so instead of a bare ENXIO."""
    try:
        is_sock = stat.S_ISSOCK(os.stat(path).st_mode)
    except OSError:
        return
    if is_sock:
        raise ConfigError(
            f"--csv {path} is a Unix socket; write to a file, FIFO or /dev/stdout instead"
        )


def _remove_quietly(p):
    try:
        os.remove(p)
    except OSError:
        pass


def _new_file_mode(real, shown):
    """0o666 minus the umask, read from an empty probe file instead of calling os.umask
    (which changes process-wide state)."""
    fd, probe = _temp_sibling(real, shown, 0o666)
    try:
        return stat.S_IMODE(os.fstat(fd).st_mode)
    finally:
        os.close(fd)
        _remove_quietly(probe)


def _temp_sibling(real, shown, mode):
    """A new empty file next to real, created with mode (the umask still narrows it).
    Errors name the path the user gave, not the temp name."""
    d = os.path.dirname(real)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    for _ in range(100):
        tmp = os.path.join(d, f".bbwarden-{secrets.token_hex(8)}.tmp")
        try:
            return os.open(tmp, flags, mode), tmp
        except FileExistsError:
            continue
        except OSError as e:
            raise OSError(e.errno, e.strerror, shown) from None
    raise FileExistsError(17, "no free temporary file name", shown)


def get_ws(args, env=None, **kw):
    if args.demo:
        return demo_workspace(), None
    backend = backend_from_env(env, insecure=getattr(args, "insecure", False), **kw)
    return backend.load(), backend


def build_parser():
    p = Parser(prog="bbwarden", description="Bitbucket least-privilege and offboarding")
    p.add_argument("--version", action="version", version=f"bbwarden {__version__}")
    common = Parser(add_help=False)
    common.add_argument(
        "--demo", action="store_true", help="use built-in mock workspace"
    )
    common.add_argument("--csv", metavar="OUT", help="also write results to CSV")
    common.add_argument(
        "--raw-csv",
        action="store_true",
        help="keep control and format characters in CSV cells instead of escaping them",
    )
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
EXIT_INCOMPLETE = 3  # finished, but part of the inventory could not be loaded
EXIT_BROKEN_PIPE = 141  # 128 + SIGPIPE, as shells report `bbwarden ... | head`


def stdout_to_devnull():
    """stdout's reader went away: point stdout's file descriptor at os.devnull so later
    writes and the final flush at exit cannot raise again ("Exception ignored ...")."""
    try:
        fd = sys.stdout.fileno()
        devnull = os.open(os.devnull, os.O_WRONLY)
    except (AttributeError, OSError, ValueError):
        return
    try:
        os.dup2(devnull, fd)
    except OSError:
        pass
    finally:
        os.close(devnull)


def is_pipe_error(e):
    """A write to stdout failed because its reader is gone. Windows reports a closed
    pipe as EINVAL, so there (only) that counts too (best effort)."""
    if isinstance(e, BrokenPipeError):
        return True
    if not isinstance(e, OSError):
        return False
    return e.errno == errno.EPIPE or (os.name == "nt" and e.errno == errno.EINVAL)


def stdout_call(fn):
    """The one place that touches stdout. Runs fn(sys.stdout) and returns "ok", "pipe"
    (the reader is gone) or "error" (any other write error, reported once on stderr).
    On a failure stdout is pointed at os.devnull, so no later write and no flush at exit
    can raise again ("Exception ignored ...", exit 120). A missing stdout (`>&-`, so
    sys.stdout is None) or an already closed one is skipped."""
    out = sys.stdout
    if out is None:
        return "ok"
    try:
        fn(out)
        return "ok"
    except ValueError:  # I/O on a closed file object
        return "ok"
    except OSError as e:
        stdout_to_devnull()
        if is_pipe_error(e):
            return "pipe"
        print(
            f"error: cannot write to stdout: {escape(e.strerror or e)}", file=sys.stderr
        )
        return "error"


def flush_stdout():
    return stdout_call(lambda out: out.flush())


def final_code(code, state):
    """Exit code after the last stdout flush. A gone reader only turns success into 141;
    an unwritable stdout turns success, 3 and 141 into 1. 2, 1, 130 and error messages
    (sys.exit("error: ...")) always win."""
    if state == "pipe" and code in (EXIT_OK, None):
        return EXIT_BROKEN_PIPE
    if state == "error" and code in (EXIT_OK, None, EXIT_INCOMPLETE, EXIT_BROKEN_PIPE):
        return EXIT_ERROR
    return code


def main(argv=None, env=None, **kw):
    """Run bbwarden, then flush stdout through stdout_call on every way out (normal
    return, sys.exit from argparse --help/--version or an error, Ctrl-C), so a closed or
    unwritable stdout gives 141 or 1 instead of a traceback or exit 120."""
    try:
        code = _main(argv, env, **kw)
    except SystemExit as e:
        raise SystemExit(final_code(e.code, flush_stdout())) from None
    return final_code(code, flush_stdout())


def _main(argv=None, env=None, **kw):
    try:  # Ctrl-C while argparse runs: same exit 130 as later, never a traceback
        args = build_parser().parse_args(argv)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        sys.exit(130)
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
        interrupted = isinstance(e.error, KeyboardInterrupt)
        why = "Ctrl-C" if interrupted else "a failure"
        print(
            f"\nAPPLY STOPPED: {len(e.done)} of {total} steps finished before {why}.",
            file=sys.stderr,
        )
        for d in e.done:
            print(f"  done    {escape(d)}", file=sys.stderr)
        if interrupted:  # the request may or may not have reached the server
            print(
                f"  INTERRUPTED {escape(e.failed)} (may or may not have happened)",
                file=sys.stderr,
            )
        else:
            print(f"  FAILED  {escape(e.failed)}", file=sys.stderr)
        for p in e.pending:
            print(f"  not run {escape(p)}", file=sys.stderr)
        print(
            "Re-run the same command (without --apply first) to see what is left.",
            file=sys.stderr,
        )
        if interrupted:
            print("interrupted", file=sys.stderr)
            sys.exit(130)
        sys.exit(f"error: {escape(core.describe_error(e.error))}")
    except (BBWardenError, core.BadIdpFile) as e:
        sys.exit(f"error: {escape(e)}")
    except OSError as e:
        if e.filename:
            sys.exit(
                f"error: cannot open {escape(e.filename)}: {escape(e.strerror or e)}"
            )
        sys.exit(f"error: {escape(e.strerror or e)}")
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        sys.exit(130)
    except Exception as e:  # noqa: BLE001 - last resort: never a raw traceback
        print("error: unexpected internal error; details follow", file=sys.stderr)
        try:
            lines = _exc_lines(e, safe=True)  # frames kept, exception types only
        except (Exception, RecursionError):  # noqa: BLE001
            lines = [escape(f"{type(e).__name__}: <traceback unavailable>")]
        for ln in lines:
            print(ln, file=sys.stderr)
        sys.exit(EXIT_ERROR)


def _check_writable(path):
    """Fail before any output if the CSV path cannot be written. Never creates, truncates
    or removes the target itself: an existing file is opened for append only, and the
    directory is probed with a temporary sibling (write_csv renames one into place)."""
    if _is_stdout(path):  # written through stdout itself; the folder does not matter
        return
    _refuse_socket(path)
    if _is_special(path):  # opening a FIFO here would block or eat the reader's EOF
        if not os.access(path, os.W_OK):
            raise PermissionError(13, "Permission denied", path)
        return
    real = os.path.realpath(path)  # a symlink: the target and its folder are what count
    if os.path.isdir(real):
        raise IsADirectoryError(21, "Is a directory", path)
    if os.path.lexists(real):
        with open(real, "a", newline=""):
            pass
    fd, tmp = _temp_sibling(real, path, 0o600)
    os.close(fd)
    os.remove(tmp)


def _run(args, env, **kw):
    if args.csv:
        _check_writable(args.csv)
        if args.raw_csv:
            print(
                "WARNING: --raw-csv: CSV cells keep control and format characters "
                "(terminal escapes, bidi overrides); open the file with care",
                file=sys.stderr,
            )
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
                try:
                    status = core.load_idp_csv(args.idp_file)
                except UnicodeError as e:
                    where = f" at byte {e.start}" if hasattr(e, "start") else ""
                    raise ConfigError(
                        f"--idp-file {args.idp_file} is not valid UTF-8{where}; "
                        "export it as UTF-8"
                    ) from None
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
    out = _Stdout()
    out.print(table(rows, cols))
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
        out.print(f"\n{note}")
    for n in ws.notes:
        print(f"NOTE: {escape(n)}", file=sys.stderr)
    if ws.notes:  # every note is a part of the inventory that could not be loaded
        print(
            "INCOMPLETE: part of the inventory could not be loaded (see NOTE lines), so "
            "these results may miss access; exit code 3",
            file=sys.stderr,
        )
    if args.csv:
        try:
            state = write_csv(rows, args.csv, cols, raw=args.raw_csv)
        except OSError as e:  # a FIFO reader left
            if not is_pipe_error(e):
                raise
            state = "pipe"
        out.merge(state)
    # Precedence: 2 (raised earlier), then 1, then 3, then 141, then 0.
    if ws.manual or out.state == "error":
        return EXIT_ERROR
    if ws.notes:
        return EXIT_INCOMPLETE
    return EXIT_BROKEN_PIPE if out.state == "pipe" else EXIT_OK


class _Stdout:
    """stdout output of one run. After a failure (see stdout_call) the rest of the run
    (stderr reports, CSV, exit code) goes on and later stdout writes are skipped."""

    def __init__(self):
        self.state = "ok"

    def merge(self, state):
        if self.state == "ok":
            self.state = state

    def print(self, text):
        if self.state == "ok":
            self.state = stdout_call(lambda out: (print(text, file=out), out.flush()))


if __name__ == "__main__":
    sys.exit(main())
