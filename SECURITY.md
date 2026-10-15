# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately. Do not open a public issue, pull request or
discussion for a suspected vulnerability.

- While this repository is private, contact the maintainer, Christopher Hickman
  (@chriswayneh), privately on GitHub. GitHub private vulnerability reporting will be turned
  on when the repository goes public; until then it is not available here.
- Include the bbwarden version (`bbwarden --version`), the command you ran, what you expected
  and what happened. Redact tokens, passwords and internal hostnames.
- If you think a credential was exposed, rotate it first. Deleting output or commits is not
  enough.

You will get an acknowledgement as soon as practical. Fixes are released as a new patch
version, and the CHANGELOG Security section describes them.

## Supported versions

| Version | Supported |
| --- | --- |
| 0.2.1 | Yes (https only, redirects refused) |
| 0.2.0 | No: upgrade to 0.2.1 (it allowed http:// to localhost and followed redirects) |
| 0.1.x | No (demo only, no live hardening) |

## Security design notes

- **https only (since 0.2.1).** `BBWARDEN_URL` and `CROWD_URL` must use `https://`. Plain `http://` is
  refused for every host, loopback included, unless you pass `--insecure`, which allows it
  and prints a warning on stderr. Use it only for a local test server. A URL without a
  hostname (for example `https://` or `https:x`) is always refused.
- **No redirects (since 0.2.1).** Every request is sent with redirects disabled, and the
  sessions allow zero redirects. A 3xx response, whether requests or bbwarden sees it, is an
  error (`redirect refused: <status> to <host>`) that names only the status and the target
  host, so credentials are never replayed to another origin or over http.
- **Exact Cloud detection.** Credentials go to Bitbucket Cloud only when the hostname is
  exactly `bitbucket.org` or `api.bitbucket.org`. Pagination links must match the base URL
  scheme, host and port, so credentials never follow a link to another origin.
- **No secrets in output.** Credentials come only from environment variables, never from
  command-line arguments. Error messages name missing variables but never print their values,
  and they drop URL query strings and response bodies.
- **Dry run by default.** `regroup` and `offboard` only print a plan unless you pass `--apply`.
  `regroup` never picks a group whose grant would widen anyone's access. On failure, `--apply`
  reports exactly which steps finished, failed and were not run.
- **Safe exports.** CSV output neutralizes spreadsheet formulas.
- **Least privilege.** Read commands need admin read only. Parts that need more rights (global
  admins, workspace owners) are skipped with a `NOTE:` instead of failing.
