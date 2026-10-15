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
    code = 1
    try:
        code = main()
        sys.stdout.flush()
    except OSError as e:
        from bbwarden.cli import after_final_flush_break, is_pipe_error

        if not is_pipe_error(e):
            raise
        code = after_final_flush_break(code)
    sys.exit(code)
