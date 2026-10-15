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

Live mode reads `BBWARDEN_URL`, `BBWARDEN_USER` and `BBWARDEN_TOKEN`. Milestone 1 supports
live read-only scans against Data Center; live Cloud, live Crowd lookup and live `--apply`
are planned for milestone 2.

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
REPO  USER  ACTION   DETAIL
----  ----  -------  -------------------------------------------------------
api   bob   replace  remove direct ADMIN; grant group devs ADMIN
api   erin  manual   no group contains erin; create one or keep direct WRITE

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

## License

MIT
