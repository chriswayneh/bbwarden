# Changelog

All notable changes to bbwarden are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `--insecure` flag to allow `http://` for `BBWARDEN_URL` and `CROWD_URL` (local test servers),
  with a warning on stderr.
- `CROWD_APP_PASSWORD`, matching crowdkeeper.
- SECURITY.md: private vulnerability reporting, supported versions, security design notes.

### Changed
- `http://` is refused for every host unless `--insecure` is given. This replaces the
  automatic `localhost` and `127.0.0.1` exception.

### Deprecated
- `CROWD_PASSWORD`: still accepted with a warning on stderr. `CROWD_APP_PASSWORD` wins when
  both are set.

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
