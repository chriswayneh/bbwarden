# Terminal demo

The README GIF replays actual output captured from the published
`bbwarden` **v0.2.5** package on 2026-11-05 (America/Chicago), using only the
built-in `--demo` mock workspace. Timing is adjusted for README readability.
It is a recorded replay, not a live Bitbucket or Crowd session.

## What it shows

1. Confirm the installed version (`0.2.5`).
2. `bbwarden who api --demo` — effective access for the fictional `api` repo
   (direct, group, project, and global admin sources; one DISABLED user).
3. `bbwarden direct --demo` — direct user grants that skip groups.
4. `bbwarden orphans --demo --idp crowd` — access held by identities disabled
   in the built-in Crowd mock.

## Run it yourself

Use Python 3.9 or newer in an isolated environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install "git+https://github.com/chriswayneh/bbwarden.git@v0.2.5"

.venv/bin/bbwarden --version
.venv/bin/bbwarden who api --demo
.venv/bin/bbwarden direct --demo
.venv/bin/bbwarden orphans --demo --idp crowd
```

`--demo` uses the built-in mock workspace only. No Bitbucket URL, Crowd URL,
token, or password is required or read. Do not set `BBWARDEN_*` or `CROWD_*`
environment variables for this walkthrough.

## Re-record the GIF

Requires [vhs](https://github.com/charmbracelet/vhs) (and `ttyd`) plus a
monospace font such as JetBrains Mono:

```bash
./scripts/record-demo.sh
```

That script stages a throwaway directory with `mktemp -d`, installs v0.2.5 into
a temporary venv, records `docs/assets/demo.gif` from `scripts/demo.tape`, and
starts no Docker containers. It never passes credentials on the command line.

## Text alternative

The [Quick start](../README.md#quick-start) section shows `bbwarden who api --demo`
in text.
