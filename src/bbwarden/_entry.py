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
    code: object = 1
    try:
        code = main()
    except SystemExit as e:
        code = e.code
    from bbwarden.cli import final_code, flush_stdout

    sys.exit(final_code(code, flush_stdout()))
