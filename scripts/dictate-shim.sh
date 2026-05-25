#!/usr/bin/env bash
# dictate launcher shim — runs dictate from its repo .venv regardless of cwd.
# Resolves the repo via DICTATE_HOME env var or the default ~/dictate.
set -euo pipefail

REPO="${DICTATE_HOME:-$HOME/dictate}"
if [[ ! -d "$REPO/.venv" ]]; then
    echo "dictate: .venv not found at $REPO/.venv" >&2
    echo "  Set DICTATE_HOME or run ./install.sh in the repo." >&2
    exit 1
fi

# Load user env (matches run.sh behavior so secrets like OPENROUTER_API_KEY work).
ENV_FILE=""
if   [[ -f "$HOME/.dictate.env" ]]; then ENV_FILE="$HOME/.dictate.env"
elif [[ -f "$REPO/.env"          ]]; then ENV_FILE="$REPO/.env"
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

cd "$REPO"
exec "$REPO/.venv/bin/python" -m dictate "$@"
