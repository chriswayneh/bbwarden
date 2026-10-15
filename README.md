# bbwarden

Least-privilege and offboarding CLI for Bitbucket (Cloud and Data Center), built on
[atlassian-python-api](https://github.com/atlassian-api/atlassian-python-api).

bbwarden answers "who can touch this repo, and why?", finds direct grants that bypass
groups, flags access held by disabled identities, and plans (or applies) fixes. Fix
commands are dry-run plans unless you pass `--apply`.

## Install

```
pip install -e .
bbwarden --version    # bbwarden 0.2.1
```

## Quick start (no Bitbucket needed)

Every command takes `--demo`, which uses a built-in mock workspace with a few planted
findings, and `--csv out.csv` to save results.

```
bbwarden who api --demo
bbwarden direct --demo
bbwarden orphans --idp crowd --demo
bbwarden regroup api --demo
bbwarden offboard dave --demo
```

## Commands

| Command | What it does |
| --- | --- |
| `who <repo or project>` | Access per person and its source (direct, group, project, global admin, public). See "What `who` covers" |
| `direct` | Direct user grants that skip groups |
| `orphans --idp crowd or csv` | People with access who are disabled in Crowd or an IdP CSV export (`--idp-file`, columns `user,active`), plus people the export does not list (`missing`) |
| `regroup <repo> [--apply]` | Plan replacing direct grants with group grants |
| `offboard <user> [--apply] [--skip-memberships]` | Plan removing a user's direct repo and project grants, group memberships, and global permissions (last) |

## What `who` covers

`who` reports access from:

- direct repo grants, repo group grants, project grants and project group grants;
- Data Center global `ADMIN` and `SYS_ADMIN` (users and groups), shown as `global:...` with
  ADMIN effect, and Bitbucket Cloud workspace owners, shown as `workspace:owner`;
- public repos (Data Center public repo or public project, Cloud repos that are not
  private), shown as an `(anyone)` row with `PUBLIC` in the flag column.

It does not cover: Data Center `PROJECT_CREATE` or licensed-user default permissions, branch
permissions, access keys, repo access tokens, project or workspace default permissions on
Cloud, or Cloud workspace members who only have default access. Permission names bbwarden
does not know (for example `REPO_CREATE`, `PROJECT_VIEW`) are shown as-is and treated as no
repo access, never guessed.

Loading global admins needs Data Center system admin rights; loading Cloud workspace owners
needs workspace admin rights. Without them bbwarden keeps going and prints a `NOTE:` to stderr
saying that part was not loaded, so the result may be incomplete.

`offboard` runs the global step last. On Data Center it is "remove all global permissions"
(one API call that drops every global permission the user holds), and DETAIL shows the
user's actual level, for example `SYS_ADMIN` or `ADMIN`. On Cloud, workspace owners cannot be
removed by API: the step is recorded as MANUAL, every other removal still runs, bbwarden
prints which steps finished and which are left to stderr, and exits with status 1. Remove the
owner in Workspace settings. Any other failure of the global step (for example 401, 403, 5xx
or a network error on Data Center) is a normal partial failure. If an earlier step fails, the
global step is listed as "not run".

## Live use

Set credentials in the environment (never on the command line):

| Variable | Meaning |
| --- | --- |
| `BBWARDEN_URL` | `https://bitbucket.org` for Cloud, or your Data Center base URL. Must be `https://` (see `--insecure`). |
| `BBWARDEN_USER` | Username (Cloud: account username or email; Data Center: user or service account) |
| `BBWARDEN_TOKEN` | Cloud app password or API token; Data Center HTTP access token or password |
| `BBWARDEN_WORKSPACE` | Cloud only: workspace slug |
| `CROWD_URL`, `CROWD_APP`, `CROWD_APP_PASSWORD` | `--idp crowd` only: Crowd base URL and application credentials. The old name `CROWD_PASSWORD` still works and prints a deprecation warning when it is used. If both are set, `CROWD_APP_PASSWORD` is used and a note says `CROWD_PASSWORD` is ignored. |

Read commands need admin read on the projects and repos you scan (Data Center user
status also needs system admin read). `--apply` needs admin write.

Data Center repos are keyed `PROJECT/slug`; a bare slug works when it is unique.

Hardening:

- Every list call is paginated (Data Center `nextPageStart`, Cloud `next`).
- HTTP 429 and 503 are retried up to 5 times with exponential backoff plus jitter,
  honoring `Retry-After` (seconds or HTTP date), capped at 60 seconds per wait.
- 401 and 403 produce a clear message naming what to fix. Errors never print
  credentials or URL query strings. Missing variables are named, not echoed.
- `regroup` only picks a group when every member of that group already has at least the
  same access on the repo, so replacing a direct grant never widens anyone's access. If no
  such group exists the step is marked `manual`.
- `regroup --apply` grants the group before removing the direct grant, so access is not
  lost if a call fails midway.
- Pagination links pointing at a different host are refused, so credentials never leave
  your Bitbucket host. Network failures report the error type without echoing request details.
- Unknown permission names from the API are shown as-is instead of crashing.
- Account status shows as `UNKNOWN` in `who` when Bitbucket does not report it (always on
  Cloud; Data Center users missing from the admin user list). bbwarden never assumes active.
- If an `--apply` run fails partway, bbwarden stops, prints which steps finished, which step
  failed and which were not run, logs the same to stderr, and exits non-zero. Re-run without
  `--apply` to see the remaining plan.
- Bitbucket Cloud does not expose account status, so use `orphans --idp csv` or `--idp crowd`
  for Cloud.
- Bitbucket Cloud users are keyed by `account_id` (shown as `nickname (account_id)`).
  `offboard` accepts an account_id or a nickname; a nickname shared by several accounts is
  refused, so pass the account_id.
- Cloud is detected only when the `BBWARDEN_URL` hostname is exactly `bitbucket.org` or
  `api.bitbucket.org`.
- `BBWARDEN_URL` and `CROWD_URL` must be `https://` for every host, loopback included.
  `--insecure` allows `http://` for a local test server and prints a warning on stderr.
  There is no automatic localhost exception, so plain http is always an explicit choice.
  A URL without a hostname (`https://`, `https:x`) is refused.
- A `BBWARDEN_URL` or `CROWD_URL` with embedded credentials (`https://user:pass@host`), a query
  string or a fragment is refused with exit code 2; put them in `BBWARDEN_USER`/`BBWARDEN_TOKEN` or
  `CROWD_APP`/`CROWD_APP_PASSWORD`. Messages show URLs as scheme, host, port and path only:
  userinfo, query strings and fragments are always dropped.
- Redirects are never followed. A 3xx response stops the run with
  `error: redirect refused: <status> to <host> ...`, naming only the status and the target
  host (never the path or query); set the URL to the final `https://` address.
- Pagination links must match the base URL scheme, host and port.
- Rate-limit retries apply only to idempotent methods (GET, PUT, DELETE). A POST that gets
  429 or 503 is not retried; check the state and re-run.
- A non-JSON response is reported with its status code only, never its body.
- A grant with an unknown permission name is marked `manual` by `regroup`.
- Group membership on Cloud is read through Bitbucket's legacy 1.0 groups API, because
  2.0 has no group membership endpoint. It may change or be retired by Atlassian.
- `offboard` loads every group the user belongs to, not only groups holding a grant.
  On Data Center, membership removal fails for groups from a read-only Crowd or LDAP
  directory; remove those in the directory itself and use `offboard --skip-memberships` to
  remove only direct grants.
- In `orphans`, IdP status is matched by user key first, then by display name. On Data Center the
  key is the username. On Cloud the key is the `account_id` and the display name is the
  nickname, so a `--idp-file` row may use either; if both appear, the account_id row wins.
  A nickname shared by several Cloud accounts applies to all of them, so prefer account_ids.
- `--idp crowd` looks each user up by username (Cloud: by nickname, since Crowd does not know
  account_ids). A user Crowd does not know (404) counts as disabled; any other Crowd error
  stops the run.

`--idp csv` reads `--idp-file` with columns `user,active`. `active` must be one of
`true/1/yes/active` or `false/0/no/inactive/disabled`. Empty users, unknown values and
duplicate users are rejected with the line number. People with access who are not in the file
are reported as `missing`, so a partial export cannot look clean.

`--csv` always writes a header row, even with no results, and prefixes cells starting with
`=`, `+`, `-`, `@`, tab or carriage return (also after leading whitespace) with `'` so
spreadsheets do not run them as formulas. The CSV path is checked for writability before
anything is printed.

## Sample output

Real output from the demo workspace:

```
$ bbwarden who api --demo
REPO  USER   EFFECTIVE  SOURCES                                             FLAG
----  -----  ---------  --------------------------------------------------  --------
api   alice  ADMIN      project:CORE/group:admins, project:CORE/group:devs
api   bob    ADMIN      direct, project:CORE/group:devs
api   dave   WRITE      project:CORE                                        DISABLED
api   erin   WRITE      direct
api   root   ADMIN      global:SYS_ADMIN
```

```
$ bbwarden who web --demo
REPO  USER      EFFECTIVE  SOURCES                                             FLAG
----  --------  ---------  --------------------------------------------------  --------
web   alice     ADMIN      project:CORE/group:admins, project:CORE/group:devs
web   bob       WRITE      project:CORE/group:devs
web   carol     READ       group:ops
web   dave      WRITE      project:CORE                                        DISABLED
web   frank     READ       direct                                              DISABLED
web   root      ADMIN      global:SYS_ADMIN
web   (anyone)  READ       public                                              PUBLIC
```

```
$ bbwarden direct --demo
SCOPE    NAME   USER   PERMISSION
-------  -----  -----  ----------
project  CORE   dave   WRITE
repo     api    bob    ADMIN
repo     api    erin   WRITE
repo     infra  erin   WRITE
repo     web    frank  READ
```

```
$ bbwarden orphans --idp crowd --demo
REPO  USER   ACCESS              IDP_STATUS
----  -----  ------------------  ----------
api   dave   project:CORE:WRITE  disabled
web   dave   project:CORE:WRITE  disabled
web   frank  direct:READ         disabled
```

```
$ bbwarden regroup api --demo
REPO  USER  ACTION   GROUP  DETAIL
----  ----  -------  -----  ---------------------------------------------------------------
api   bob   replace  devs   grant group devs ADMIN; remove direct ADMIN
api   erin  manual          no granted group contains erin; create one or keep direct WRITE

DRY RUN: re-run with --apply to make these changes
```

```
$ bbwarden offboard dave --demo
SCOPE    NAME  ACTION               DETAIL
-------  ----  -------------------  ------
project  CORE  remove direct grant  WRITE

DRY RUN: re-run with --apply to make these changes
```

## Development

```
pip install -e ".[dev]"
ruff format --check .
ruff check .
mypy src
pytest -q
```

Tests run offline against demo data and a mocked HTTP session.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success (including dry runs) |
| 1 | Runtime error: Bitbucket or Crowd error, unknown repo or user, bad IdP file, file error, an `--apply` that stopped partway, or an `offboard --apply` with MANUAL steps left |
| 2 | Configuration or usage error: http refused, URL without a hostname or with embedded credentials, missing variable (for example `BBWARDEN_TOKEN`, `BBWARDEN_WORKSPACE`, Crowd credentials), `--idp csv` without `--idp-file`, or invalid arguments |

Errors are printed to stderr as `error: ...`.

## Security

See [SECURITY.md](SECURITY.md) for how to report a vulnerability privately, supported
versions and the security design.

## License

MIT
