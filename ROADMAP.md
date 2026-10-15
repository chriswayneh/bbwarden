# bbwarden roadmap

Plan for bbwarden by phase. Each phase ships something you can run from the command line. bbwarden stays CLI-only: no GUI, no web dashboard, no hosted service. Later phases do not block earlier ones. Versions are direction, not date promises.

## Current status

| Item | Details |
| --- | --- |
| **Latest release** | `v0.2.3` (2026-10-15). See [CHANGELOG.md](CHANGELOG.md). |
| **Next** | Finish Phase 2: Harden (most of it shipped in `v0.2.0`, `v0.2.1`, `v0.2.2` and `v0.2.3`) |
| **Next target** | `v0.3.0` |

## Phase map

| Phase | Name | Version | Outcome | Status |
| --- | --- | --- | --- | --- |
| **0** | Foundation | `v0.1.0` | Five commands, demo mode, live Data Center reads, CSV, tests, CI | Done |
| **1** | Connect | `v0.2.0` | Live Bitbucket Cloud, live Crowd lookup, live `--apply` | Done |
| **2** | Harden | `v0.3.0` | Retries, paging, clear errors, exit codes, safe apply, https only, no redirects, no credentials in URLs, escaped output | In progress (most shipped in `v0.2.0`, `v0.2.1`, `v0.2.2` and `v0.2.3`) |
| **3** | Report | `v0.4.0` | JSON output, severity, exit-on-findings for CI | Planned |
| **4** | Stable | `v1.0.0` | Stable CLI, flag names, report schema and exit codes | Planned |

## Phase 0: Foundation (v0.1.0)

**Goal:** Clone it and run every command in demo mode in about a minute.

- [x] `who <repo or project>`: effective access per person and where it comes from (direct, group, project)
- [x] `direct`: direct user grants that skip groups
- [x] `orphans --idp crowd|csv`: access held by users disabled in Crowd (demo) or an IdP CSV export (`user,active`)
- [x] `regroup <repo>`: plan replacing direct grants with group grants, dry run unless `--apply`
- [x] `offboard <user>`: plan removing a user from every repo, project and group, dry run unless `--apply`
- [x] `--demo` on every command with a built-in mock workspace, `--apply` changes only the demo workspace
- [x] `--csv` export
- [x] Live read-only scans against Bitbucket Data Center through atlassian-python-api (`BBWARDEN_URL`, `BBWARDEN_USER`, `BBWARDEN_TOKEN`)
- [x] Tests for the demo workspace
- [x] CI on Python 3.9 to 3.13 with pinned actions and least-privilege token

**Done when:** every command runs in demo mode as documented and CI is green. Landed as milestone 1 in commit `bb55b8b`, with CI added after. Listed as `0.1.0` in the CHANGELOG; not tagged.

## Phase 1: Connect (v0.2.0)

**Goal:** Do in live mode what demo mode already does (milestone 2 in early commits).

- [x] Live Bitbucket Cloud loading (workspaces, projects, repos, groups and permissions)
- [x] Live Crowd lookup for `orphans --idp crowd`
- [x] Live `--apply` for `regroup` and `offboard`, printing the plan first
- [x] Tests against mocked API responses for Data Center and Cloud
- [x] First tag, GitHub release and `CHANGELOG.md`

**Done when:** every command works in live mode on Data Center and Cloud, and `v0.2.0` is tagged. Done in `v0.2.0` (tag `v0.2.0`, PR #1).

## Phase 2: Harden (v0.3.0)

**Goal:** Live mode you can point at a real server without surprises.

- [x] Full pagination of every list call (`v0.2.0`)
- [x] Retries for 429 and 503 on idempotent methods with `Retry-After` and capped backoff (`v0.2.0`)
- [ ] Retries for other 5xx and connection errors
- [x] One-line `error:` messages for auth, URL and permission failures, no tracebacks (`v0.2.0`)
- [x] Documented exit codes, including partial apply (`v0.2.1`)
- [x] https only (`--insecure` to allow http), redirects never followed, no credentials, query or fragment in `BBWARDEN_URL`/`CROWD_URL` (`v0.2.1`)
- [x] Escaped terminal output (control and bidi characters shown as code points) and CSV formula guard that sees through invisible leading characters (`v0.2.2`)
- [x] IDN hostnames compared as requests sends them (`v0.2.3`)
- [ ] Known limit for `v0.2.4`: with `--raw-csv`, an escaped lone surrogate (written as `\ud800`) looks the same as a name that literally contains `\ud800`
- [ ] Known limit for `v0.2.4`: Ctrl-C during startup or argument parsing (before `main()`'s error handling) still shows Python's own traceback
- [x] `--apply` reports which steps finished, failed and were not run (`v0.2.0`)
- [ ] Warn before removing a user's last admin path
- [x] CSV formula injection escaped (`v0.2.0`)

**Done when:** live mode handles throttling, paging and partial failure cleanly and CI is green.

## Phase 3: Report (v0.4.0)

**Goal:** Feed bbwarden results into pipelines and other tools, not just terminals.

- [ ] `--format table|json|csv` on every command, with a documented JSON schema
- [ ] Severity per finding and `--fail-on SEVERITY` exit code for CI gates
- [ ] `scan` command that runs `direct` and `orphans` across the whole instance in one pass
- [ ] `--baseline FILE` to report only new findings since a saved scan

**Done when:** a scheduled CI job can run `bbwarden scan` and fail on new findings.

## Phase 4: Stable (v1.0.0)

**Goal:** A contract other people can build on.

- [ ] Freeze command names, flags, JSON schema and exit codes
- [ ] Deprecation policy for anything that changes after `v1.0.0`
- [ ] Published to PyPI with signed releases
- [ ] Docs for the Bitbucket and Crowd permissions each command needs

**Done when:** the contract is documented, tested and released to PyPI.

## Out of scope

- A GUI, web dashboard or hosted service. bbwarden is CLI-only.
- Continuous monitoring or alerting. It is a point-in-time review tool.
- Code, branch or pipeline settings. bbwarden covers who has access, not what they do with it.
- Silent changes. Every fix stays a dry run unless `--apply` is given.
