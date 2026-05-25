#!/usr/bin/env bash
# Build dictate.app via py2app
#
# Usage:
#   ./scripts/build_app.sh           # production bundle (slow, ~5-10 min)
#   ./scripts/build_app.sh --alias   # alias mode (fast, dev — symlinks to source)
#   ./scripts/build_app.sh --clean   # remove build/ and dist/ first

set -euo pipefail
cd "$(dirname "$0")/.."

CLEAN=0
ALIAS=0
for arg in "$@"; do
  case "$arg" in
    --clean) CLEAN=1 ;;
    --alias) ALIAS=1 ;;
    *) echo "Unknown arg: $arg" >&2; exit 1 ;;
  esac
done

# Verify py2app installed
if ! python3 -c "import py2app" 2>/dev/null; then
  echo "py2app not installed. Run: pip install py2app" >&2
  exit 1
fi

# Verify we're on macOS
if [[ "$(uname)" != "Darwin" ]]; then
  echo "Build only supported on macOS." >&2
  exit 1
fi

if [[ $CLEAN -eq 1 ]]; then
  echo "Cleaning build/ and dist/..."
  rm -rf build dist
fi

ARGS=("py2app")
if [[ $ALIAS -eq 1 ]]; then
  ARGS+=(-A)
  echo "Building dictate.app in ALIAS mode (fast, dev)..."
else
  echo "Building dictate.app in PRODUCTION mode (slow)..."
fi

python3 setup_app.py "${ARGS[@]}"

APP_PATH="dist/dictate.app"
if [[ ! -d "$APP_PATH" ]]; then
  echo "Build failed: $APP_PATH not created" >&2
  exit 1
fi

echo ""
echo "✓ Built: $APP_PATH"
echo ""
echo "Next steps:"
echo "  open $APP_PATH                  # launch from Finder"
echo "  open dist/dictate.app           # or via path"
echo "  ./scripts/sign_app.sh           # code-sign (requires Developer ID)"
echo "  ./scripts/notarize_app.sh       # notarize for distribution"
echo ""
echo "For distribution, see docs/build-app.md."
