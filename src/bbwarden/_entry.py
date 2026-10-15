"""Console-script entry point. It imports only os and sys before the handler is in
place, so a Ctrl-C while the rest of bbwarden (and atlassian-python-api, requests, ...)
is still importing exits 130 with "interrupted" instead of a traceback. A Ctrl-C during
Python's own start-up, before this module runs, cannot be caught by any code in
bbwarden."""

from __future__ import annotations

import os
import sys


def _fd_to_devnull(stream):
    try:
        fd = stream.fileno()
        devnull = os.open(os.devnull, os.O_WRONLY)
    except (AttributeError, OSError, ValueError):
        return
    try:
        os.dup2(devnull, fd)
    except OSError:
        pass
    finally:
        os.close(devnull)


class SafeStderr:
    """sys.stderr that cannot fail: when a write or flush fails (`2>/dev/full`), the
    descriptor is pointed at os.devnull and the run, and its exit code, go on. This also
    covers the `error: ...` message Python prints for sys.exit("error: ...") and the
    final flush at exit, which would otherwise turn any exit code into 120."""

    def __init__(self, raw):
        self._raw = raw

    def write(self, s):
        try:
            return self._raw.write(s)
        except (OSError, ValueError):
            _fd_to_devnull(self._raw)
            return len(s)

    def flush(self):
        try:
            self._raw.flush()
        except (OSError, ValueError):
            _fd_to_devnull(self._raw)

    def __getattr__(self, name):
        return getattr(self._raw, name)


def run():
    if sys.stderr is not None and not isinstance(sys.stderr, SafeStderr):
        sys.stderr = SafeStderr(sys.stderr)
    try:
        from bbwarden.cli import main
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        sys.exit(130)
    code: int | str | None = 1
    try:
        code = main()
    except SystemExit as e:
        code = e.code
    from bbwarden.cli import final_code, flush_stderr, flush_stdout

    code = final_code(code, flush_stdout())
    flush_stderr()
    sys.exit(code)
