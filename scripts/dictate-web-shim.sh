#!/usr/bin/env bash
# dictate-web launcher shim — runs the WebUI from its repo .venv regardless of cwd.
# Resolves the repo via DICTATE_HOME env var or the default ~/dictate.
set -euo pipefail

REPO="${DICTATE_HOME:-$HOME/dictate}"
if [[ ! -d "$REPO/.venv" ]]; then
    echo "dictate-web: .venv not found at $REPO/.venv" >&2
    echo "  Set DICTATE_HOME or run ./install.sh in the repo." >&2
    exit 1
fi

cd "$REPO"
exec "$REPO/.venv/bin/python" -m dictate.webui "$@"
