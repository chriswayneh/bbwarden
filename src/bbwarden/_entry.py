"""Console-script entry point. It imports only sys before the handler is in place, so a
Ctrl-C while the rest of bbwarden (and atlassian-python-api, requests, ...) is still
importing exits 130 with "interrupted" instead of a traceback. A Ctrl-C during Python's
own start-up, before this module runs, cannot be caught by any code in bbwarden."""

import sys


def run():
    try:
        from bbwarden.cli import main
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        sys.exit(130)
    try:
        code = main()
        sys.stdout.flush()
    except BrokenPipeError:
        from bbwarden.cli import broken_pipe_exit

        broken_pipe_exit()
    sys.exit(code)
