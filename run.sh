#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Load environment so the app sees secrets like OPENROUTER_API_KEY regardless of
# how it was launched (login shell, Finder, launchd, nohup from any shell, …).
#
# Source order (later wins):
#   1. ~/.dictate.env or ./.env   — user-managed KEY=value file (gitignored)
#   2. `launchctl getenv` for known keys — picks up macOS GUI env
ENV_FILE=""
if   [[ -f "$HOME/.dictate.env" ]]; then ENV_FILE="$HOME/.dictate.env"
elif [[ -f "./.env"            ]]; then ENV_FILE="./.env"
fi
if [[ -n "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi
for KEY in OPENROUTER_API_KEY; do
    if [[ -z "${!KEY:-}" ]]; then
        VAL="$(launchctl getenv "$KEY" 2>/dev/null || true)"
        [[ -n "$VAL" ]] && export "$KEY=$VAL"
    fi
done

# shellcheck source=/dev/null
source .venv/bin/activate
exec python -m dictate "$@"
