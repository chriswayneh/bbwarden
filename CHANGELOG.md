# Changelog

All notable changes to bbwarden are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.2.4] - 2026-10-15

### Fixed
- `offboard` now removes every direct global permission on Data Center (for example
  `LICENSED_USER` or `PROJECT_CREATE`), not only admin levels, so offboarding no longer
  leaves global access behind. Data Center users whose only access is a direct global
  permission (for example `LICENSED_USER`) are now loaded into the inventory so `offboard`
  finds them; the `who`, `direct`, `orphans` and `regroup` reports are unchanged.
- Pagination fails loudly with an `incomplete pagination` error (exit 1) on a page without a
  `values` list, a Data Center page that is neither the last nor has a `nextPageStart`, or a
  repeated cursor, instead of silently using a partial list.
- `regroup --apply` re-reads the group's members right before each grant and stops if a
  member added since the plan would gain access.
- `regroup --apply` lists rows marked `manual` as `MANUAL` and exits 1 instead of printing
  `APPLIED` and exiting 0.
- An IdP CSV with duplicate column names (also after trimming spaces) is refused.
- Ctrl-C during `--apply` prints which steps finished, which was interrupted and which were
  not run, then exits 130.
- `--csv` never removes or truncates an existing file while checking that the path is
  writable, and writes through a temporary file renamed into place, so a failed write keeps
  the old file. A symlink is followed: its target is updated and the link stays. An existing
  target that is not a regular file (a FIFO, `/dev/stdout`, `/dev/fd/N` from process
  substitution, a character device) is written directly, with no temporary file or rename,
  as before. A Unix socket target is refused before any output with a configuration error
  (exit 2). A target that is the same file as stdout (`--csv out.csv > out.csv` or `>>`) is
  written through stdout after the table instead of being replaced. The CSV is always UTF-8,
  whatever the console encoding (also for `/dev/stdout` and `/dev/tty`).
- Crowd status needs a real boolean `active` flag; a string, number or missing flag is an
  error instead of a guess.
- With `--raw-csv`, lone surrogates are written as U+FFFD, so they can no longer be confused
  with a name that literally contains `\ud800` (ROADMAP known limit). A U+FFFD in raw CSV
  can no longer be told apart from a real U+FFFD in the data; use the default escaped CSV
  when that matters.
- Ctrl-C while bbwarden is still importing or parsing arguments prints `interrupted` and
  exits 130 instead of a Python traceback (ROADMAP known limit). The console script now
  points at `bbwarden._entry:run`.

### Changed
- CSV writes are atomic, so `--csv` needs a writable folder: a writable file in a read-only
  folder is now refused before any output (exit 1). The rename creates a new file, so the
  old file's owner, ACLs and extended attributes are not kept and hard links to it keep the
  old content; only the permission bits are copied.
- New exit code 3: the command finished but part of the inventory could not be loaded
  (`NOTE:` lines plus an `INCOMPLETE:` line on stderr). Previously this exited 0.

### Security
- The temporary CSV file is owner-only (0o600) while the access inventory is written and
  gets its final mode (the old file's, or 0o666 minus the umask for a new file) just
  before the rename, so other local users cannot read a private report mid-rewrite. The
  umask is read from an empty probe file, never changed.
- Known limit: the target path is resolved once; an attacker who can write to a folder on
  that path can redirect the write between resolve and rename.

## [0.2.3] - 2026-10-15

### Fixed
- IDN hosts (for example `BBWARDEN_URL=https://bücher.example` or
  `https://büro.my_host.internal`) are no longer refused as cross-host. The origin check
  prepares each URL with requests itself and compares the host it would send: ASCII labels
  are kept as written (so `bitbucket_server` works) and compared case-insensitively, and
  non-ASCII labels are encoded per label with IDNA2008, so hosts that only IDNA2003 would
  merge (`faß` and `fass`, `ς` and `σ`) stay different. A host that cannot be parsed or
  encoded is never treated as the same origin. `idna>=2.5,<4` and `urllib3>=1.26,<3`
  (both already required by requests) are now declared dependencies: bbwarden imports
  urllib3, and urllib3 uses idna to encode the labels; `hypothesis` is in the
  `dev` extra for a differential test against requests.

### Added
- Dependabot configuration: weekly pip and GitHub Actions updates, minor and patch grouped.

## [0.2.2] - 2026-10-15

### Security
- Table cells and every stderr line built from data (`error:`, `MANUAL`, `NOTE:`, apply
  reports and log lines) escape control and format characters: C0, DEL, C1 and Unicode
  categories Cc, Cf and Cs are printed as escaped code points (for example `\x1b`, `\u202e`).
  A repo, user, group or IdP name can no longer inject terminal escape sequences or bidi
  overrides. CSV output keeps the original data. Line and paragraph separators (U+2028,
  U+2029), private-use and unassigned code points are escaped too, and a backslash is shown
  as `\\` so literal text cannot pass for an escape. Log messages are escaped with their
  arguments, and tracebacks line by line with each exception message and its notes
  escaped as one unit (chained exceptions and ExceptionGroup included; chains, group
  nesting and members per group are cut at 50 and rendering can never make a log call
  fail), so a newline in a name or error cannot forge a log line. argparse errors are
  escaped.
  Table columns are aligned by display width (wide characters 2; combining,
  nonspacing and enclosing marks, including variation selectors, 0).
- The CSV formula guard skips leading control and format characters (for example `\u200b`
  or `\x1b`) before checking for `=`, `+`, `-` or `@`, so `\u200b=cmd` is neutralized.
- CSV cells are escaped like terminal output by default (ESC, OSC 8 links, U+202E, U+2028,
  U+2029 and C1 never raw); the file is written as UTF-8. New `--raw-csv` on every command
  keeps the original characters, prints a warning, and still neutralizes formulas. Lone
  surrogates are escaped in both modes, so they no longer crash `--csv`.
- An `--idp-file` that is not UTF-8 is a clean configuration error (exit 2) instead of a
  traceback; a UTF-8 BOM is accepted. Any other unexpected error prints a traceback
  with frame lines and exception types only (no messages or notes, which could carry
  secrets) and exits 1; log tracebacks use the same type-only rendering. Ctrl-C prints
  `interrupted` and exits 130.
- Log lines name the failed step without quotes, escaped once.
- `requests>=2.32.4` (fixes CVE-2024-47081, .netrc credential leak).

## [0.2.1] - 2026-10-15

### Added
- `--insecure` flag to allow `http://` for `BBWARDEN_URL` and `CROWD_URL` (local test servers),
  with a warning on stderr.
- `CROWD_APP_PASSWORD`, matching crowdkeeper.
- `mypy` (with `check_untyped_defs`), `ruff` and `types-requests` in the `dev` extra; code is
  `ruff format`ted.
- SECURITY.md: private contact while the repo is private, supported versions, security design notes.

### Changed
- **Breaking**: `http://` is refused for every host unless `--insecure` is given. This drops
  the automatic `localhost` and `127.0.0.1` exception from 0.2.0; add `--insecure` for a
  local http test server. URLs without a hostname are refused.
- Configuration errors (http refused, no hostname, missing variable) print `error: ...` to
  stderr and exit with code 2. Other errors still exit with code 1.

### Security
- HTTP redirects are refused on every Bitbucket and Crowd request (`allow_redirects=False`
  and `max_redirects=0` on the sessions). A 3xx response, or a response that was redirected
  anyway, is an error (`redirect refused: <status> to <host>`) naming only the status and
  the target host.
- `BBWARDEN_URL` and `CROWD_URL` with embedded credentials (`https://user:pass@host`), a query
  string or a fragment are refused as a configuration error (exit 2) without echoing them,
  as is a URL that is not a valid URL (for example a broken IPv6 host or port).
- URLs in error messages keep only scheme, host, port and path; userinfo, query strings and
  fragments are dropped (IPv6 hosts handled). Previously userinfo could appear in redirect,
  network and 401/403 messages.
- A failed `--apply` step that raises an unexpected (non-bbwarden) exception is reported
  and logged by exception type only, since its message could carry secrets.

### Deprecated
- `CROWD_PASSWORD`: still accepted, with a deprecation warning on stderr when it is used. If
  `CROWD_APP_PASSWORD` is also set, it wins and a note says `CROWD_PASSWORD` is ignored.

## [0.2.0] - 2026-10-15

### Added
- Live Bitbucket Cloud and Data Center backends built on atlassian-python-api sessions.
- Live `--idp crowd` lookup, and live `regroup --apply` and `offboard --apply`.
- Pagination for every list call (Data Center `nextPageStart`, Cloud `next`).
- Retries for HTTP 429 and 503 on idempotent methods, with exponential backoff and jitter,
  honoring `Retry-After`.
- `--version` flag.
- `offboard --skip-memberships` to remove only direct grants.
- `offboard` loads every group the user belongs to, not only groups that hold a grant.
- When `--apply` fails partway, bbwarden prints and logs the steps that finished, the step
  that failed, and the steps not run.
- Tests on mocked HTTP for pagination, retries, auth errors, and both live backends.
- `who` includes Data Center global `ADMIN`/`SYS_ADMIN` users and groups, Cloud workspace
  owners, and public repos (`(anyone)` row). Parts that need extra rights and cannot be loaded
  produce a `NOTE:` on stderr. `offboard` removes global permissions as its last step
  ("remove all global permissions" on Data Center, showing the actual level in DETAIL).
  If that step cannot be done by API (Cloud workspace owners), it is recorded as a manual
  step, other removals are kept, the summary goes to stderr, and bbwarden exits with status 1.
  Other errors on that step are normal partial failures, and the step is listed as "not run"
  when an earlier step fails.
- `orphans` reports people with access who are missing from the IdP export.

### Changed
- Bitbucket Cloud users are keyed by `account_id` and shown as `nickname (account_id)`.
- Account status is `UNKNOWN` when Bitbucket does not report it, instead of active.
- `regroup` plan rows show the display label.
- The version is read from `bbwarden.__version__`.
- `--idp csv` is strict: unknown `active` values, empty users, duplicates and missing columns
  are rejected with the line number.
- `--csv` always writes a header row, with command-specific columns, and the path is
  checked for writability before any output. Displayed columns are defined per command.
- `regroup` says "no granted group" when it can only see groups that hold a grant.

### Fixed
- `regroup --apply` could give repo access to group members who had none. It now only picks
  a group whose members all already have at least that access; otherwise the step is manual.
- A grant with an unknown permission name is marked manual instead of being sent back as is.
- Ambiguous or unknown users are refused by `offboard` instead of guessed.
- Cloud group listings without a member list now stop the run instead of reading as empty.
- Missing or unwritable files, and OS errors without a file name, give a one-line error
  instead of a traceback.

### Security
- Cloud is detected only for the exact hosts `bitbucket.org` and `api.bitbucket.org`, so a
  Data Center token is never sent to Bitbucket Cloud by mistake.
- Pagination links must match the base URL scheme, host and port.
- `BBWARDEN_URL` must be `https://`; plain `http://` only for `localhost` and `127.0.0.1`.
- 401 and 403 errors name the fix and never print credentials or URL query strings.
- Non-JSON responses and network errors report no response body or request details.
- CSV exports neutralize spreadsheet formulas (CSV injection), also after leading whitespace.

## [0.1.0] - 2026-10-14

### Added
- First release: `who`, `direct`, `orphans`, `regroup` and `offboard` with `--demo` and
  `--csv`, a built-in demo workspace, pytest tests and a README.
