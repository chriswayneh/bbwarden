# bbwarden

Least-privilege and offboarding CLI for Bitbucket (Cloud and Data Center), built on
[atlassian-python-api](https://github.com/atlassian-api/atlassian-python-api).

bbwarden answers "who can touch this repo, and why?", finds direct grants that bypass
groups, flags access held by disabled identities, and plans (or applies) fixes. Fix
commands are dry-run plans unless you pass `--apply`.

## Install

```
pip install -e .
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
| `who <repo or project>` | Effective access per person and its source (direct, group, project) |
| `direct` | Direct user grants that skip groups |
| `orphans --idp crowd or csv` | People with access who are disabled in Crowd or an IdP CSV export (`--idp-file`, columns `user,active`) |
| `regroup <repo> [--apply]` | Plan replacing direct grants with group grants |
| `offboard <user> [--apply]` | Plan removing a user from every repo, project and group |

## Live use

Set credentials in the environment (never on the command line):

| Variable | Meaning |
| --- | --- |
| `BBWARDEN_URL` | `https://bitbucket.org` for Cloud, or your Data Center base URL. Must be `https://`. |
| `BBWARDEN_USER` | Username (Cloud: account username or email; Data Center: user or service account) |
| `BBWARDEN_TOKEN` | Cloud app password or API token; Data Center HTTP access token or password |
| `BBWARDEN_WORKSPACE` | Cloud only: workspace slug |
| `CROWD_URL`, `CROWD_APP`, `CROWD_PASSWORD` | `--idp crowd` only: Crowd base URL and application credentials |

Read commands need admin read on the projects and repos you scan (Data Center user
status also needs system admin read). `--apply` needs admin write.

Data Center repos are keyed `PROJECT/slug`; a bare slug works when it is unique.

Hardening:

- Every list call is paginated (Data Center `nextPageStart`, Cloud `next`).
- HTTP 429 and 503 are retried up to 5 times with exponential backoff plus jitter,
  honoring `Retry-After` (seconds or HTTP date), capped at 60 seconds per wait.
- 401 and 403 produce a clear message naming what to fix. Errors never print
  credentials or URL query strings. Missing variables are named, not echoed.
- `regroup --apply` grants the group before removing the direct grant, so access is not
  lost if a call fails midway.
- Pagination links pointing at a different host are refused, so credentials never leave
  your Bitbucket host. Network failures report the error type without echoing request details.
- Unknown permission names from the API are shown as-is instead of crashing.
- Bitbucket Cloud does not expose account status, so use `orphans --idp csv` or `--idp crowd`
  for Cloud.
- `--idp crowd` treats a user Crowd does not know (404) as disabled.

`--idp csv` reads `--idp-file` with columns `user,active` (`true/false`, `1/0`, `yes/no`).

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
----  ----  -------  -----  -------------------------------------------------------
api   bob   replace  devs   grant group devs ADMIN; remove direct ADMIN
api   erin  manual          no group contains erin; create one or keep direct WRITE

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
pytest -q
```

Tests run offline against demo data and a mocked HTTP session.

## License

MIT
