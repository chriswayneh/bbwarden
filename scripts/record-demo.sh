#!/usr/bin/env bash
# Re-record docs/assets/demo.gif from the published bbwarden v0.2.5 package (--demo only).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/bbwarden-demo-XXXXXX")"
VENV="$STAGE/venv"
WORK="$STAGE/work"

cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT

command -v vhs >/dev/null || { echo "vhs is required" >&2; exit 1; }
command -v ttyd >/dev/null || { echo "ttyd is required by vhs" >&2; exit 1; }

mkdir -p "$WORK"
cp "$ROOT/scripts/demo.tape" "$WORK/demo.tape"

python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install -q "git+https://github.com/chriswayneh/bbwarden.git@v0.2.5"

export BBWARDEN_BIN_DIR="$VENV/bin"
export BBWARDEN_DEMO_HOME="$WORK"
export PATH="$BBWARDEN_BIN_DIR:$PATH"

# Offline sanity: --demo must work with no Bitbucket/Crowd env.
unset BBWARDEN_URL BBWARDEN_USER BBWARDEN_PASSWORD BBWARDEN_TOKEN CROWD_URL CROWD_USER CROWD_PASSWORD || true
"$VENV/bin/bbwarden" --version >/dev/null
"$VENV/bin/bbwarden" who api --demo >/dev/null

( cd "$WORK" && vhs demo.tape )

mkdir -p "$ROOT/docs/assets"
cp "$WORK/demo.gif" "$ROOT/docs/assets/demo.gif"
echo "Wrote $ROOT/docs/assets/demo.gif"
