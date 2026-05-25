#!/usr/bin/env bash
# dictate installer
# Usage: ./install.sh [--with-ollama] [--autolaunch]
#
# By default, dictate uses Ollama (local) as its cleanup backend so your
# transcripts never leave the machine. Pass --with-ollama on a fresh Mac
# to install + pull the default model in one go.
set -euo pipefail

cd "$(dirname "$0")"
ROOT="$(pwd)"

WITH_OLLAMA=0
AUTOLAUNCH=0
for arg in "$@"; do
  case "$arg" in
    --with-ollama) WITH_OLLAMA=1 ;;
    --autolaunch)  AUTOLAUNCH=1 ;;
    -h|--help)
      sed -n '1,10p' "$0"; exit 0 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

# --- Python venv ---
PYBIN="${DICTATE_PYTHON:-}"
if [[ -z "$PYBIN" ]]; then
  for cand in python3.14 python3.12 python3.11 python3; do
    if command -v "$cand" >/dev/null 2>&1; then PYBIN="$(command -v "$cand")"; break; fi
  done
fi
if [[ -z "$PYBIN" ]]; then echo "no python3 found" >&2; exit 1; fi
if [[ ! -d .venv ]]; then
  echo "==> Creating venv with $PYBIN"
  "$PYBIN" -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate

echo "==> Installing Python deps"
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt

# --- Ollama (default cleanup backend) ---
if [[ "$WITH_OLLAMA" -eq 1 ]]; then
  if ! command -v ollama >/dev/null 2>&1; then
    echo "==> Installing Ollama via brew"
    if ! command -v brew >/dev/null 2>&1; then
      echo "Homebrew not found. Install brew first: https://brew.sh" >&2; exit 1
    fi
    brew install ollama
  fi
  echo "==> Starting ollama service"
  brew services start ollama || true
  sleep 2
  echo "==> Pulling qwen2.5:3b-instruct"
  ollama pull qwen2.5:3b-instruct || true
fi

# --- Backend reachability hint ---
if curl -fsS -o /dev/null -m 2 http://127.0.0.1:11434/v1/models; then
  echo "==> Ollama reachable at 127.0.0.1:11434"
else
  echo "WARN: Ollama not reachable. Either:"
  echo "      • Re-run with --with-ollama to install it, or"
  echo "      • Install from https://ollama.com and run \`ollama serve\`, or"
  echo "      • Set OPENROUTER_API_KEY and switch cleanup.backend to 'openrouter'"
  echo "        in config/settings.yaml (cloud — your transcripts leave the machine)."
fi

# --- LaunchAgent ---
if [[ "$AUTOLAUNCH" -eq 1 ]]; then
  PLIST_SRC="$ROOT/com.dictate.app.plist.template"
  PLIST_DST="$HOME/Library/LaunchAgents/com.dictate.app.plist"
  echo "==> Installing LaunchAgent to $PLIST_DST"
  mkdir -p "$HOME/Library/LaunchAgents"
  sed "s|__ROOT__|$ROOT|g; s|__HOME__|$HOME|g" "$PLIST_SRC" > "$PLIST_DST"
  launchctl unload "$PLIST_DST" 2>/dev/null || true
  launchctl load "$PLIST_DST"
  echo "    Loaded. To uninstall: launchctl unload $PLIST_DST && rm $PLIST_DST"
fi

# --- PATH shim ---
SHIM_TARGET_DIR=""
for CAND in /opt/homebrew/bin /usr/local/bin "$HOME/.local/bin"; do
    if [[ -d "$CAND" && -w "$CAND" ]]; then
        SHIM_TARGET_DIR="$CAND"
        break
    fi
    if [[ "$CAND" == "$HOME/.local/bin" && ! -d "$CAND" ]]; then
        mkdir -p "$CAND" 2>/dev/null && SHIM_TARGET_DIR="$CAND" && break
    fi
done
if [[ -n "$SHIM_TARGET_DIR" ]]; then
    for PAIR in "dictate:dictate-shim.sh" "dictate-web:dictate-web-shim.sh"; do
        NAME="${PAIR%%:*}"
        SRC="$ROOT/scripts/${PAIR##*:}"
        DST="$SHIM_TARGET_DIR/$NAME"
        if [[ -L "$DST" || ! -e "$DST" ]]; then
            ln -sf "$SRC" "$DST"
            echo "==> Installed PATH shim at $DST"
        else
            echo "    NOTE: $DST exists and is not a symlink — leaving it alone."
            echo "    Run \`ln -sf $SRC $DST\` manually if you want to overwrite."
        fi
    done
    case ":$PATH:" in
        *":$SHIM_TARGET_DIR:"*) ;;
        *) echo "    NOTE: $SHIM_TARGET_DIR is not on \$PATH. Add it to your shell rc." ;;
    esac
else
    echo "    NOTE: no writable bin dir on PATH for shims. Add aliases:"
    echo "      alias dictate='$ROOT/.venv/bin/python -m dictate'"
    echo "      alias dictate-web='$ROOT/.venv/bin/python -m dictate.webui'"
fi

# --- State dir ---
STATE_DIR="$HOME/Library/Application Support/dictate"
mkdir -p "$STATE_DIR"
echo "==> State dir: $STATE_DIR"

echo ""
echo "[ok] Install complete."
echo "   Run with: dictate start    (then: dictate status / stop / restart / doctor)"
echo "   Or foreground: ./run.sh"
echo "   First launch will prompt for Accessibility, Microphone, Input Monitoring permissions."
