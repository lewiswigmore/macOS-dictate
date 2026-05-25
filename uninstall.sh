#!/usr/bin/env bash
# dictate uninstaller — removes PATH shim, LaunchAgent, and (optionally) the venv.
# Leaves your config + history alone unless you pass --purge.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"

PURGE=0
for arg in "$@"; do
    case "$arg" in
        --purge) PURGE=1 ;;
        -h|--help)
            sed -n '1,5p' "$0"; exit 0 ;;
        *) echo "unknown arg: $arg" >&2; exit 2 ;;
    esac
done

# Stop any running instance
if [[ -x "$ROOT/.venv/bin/python" ]]; then
    "$ROOT/.venv/bin/python" -m dictate stop 2>/dev/null || true
fi

# LaunchAgent
PLIST_DST="$HOME/Library/LaunchAgents/com.dictate.app.plist"
if [[ -f "$PLIST_DST" ]]; then
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    rm -f "$PLIST_DST"
    echo "==> Removed LaunchAgent"
fi

# PATH shims
for CAND in /opt/homebrew/bin /usr/local/bin "$HOME/.local/bin"; do
    for NAME in dictate dictate-web; do
        SHIM_DST="$CAND/$NAME"
        if [[ -L "$SHIM_DST" ]] && [[ "$(readlink "$SHIM_DST")" == "$ROOT/scripts/"* ]]; then
            rm -f "$SHIM_DST"
            echo "==> Removed shim at $SHIM_DST"
        fi
    done
done

# Venv
if [[ -d "$ROOT/.venv" ]]; then
    rm -rf "$ROOT/.venv"
    echo "==> Removed .venv"
fi

if [[ "$PURGE" -eq 1 ]]; then
    rm -rf "$HOME/Library/Application Support/dictate"
    echo "==> Purged state dir"
    echo "    Config and history under $ROOT/config and $ROOT/logs were NOT touched."
    echo "    Delete $ROOT manually if you want them gone too."
fi

echo "[ok] Uninstall complete."
