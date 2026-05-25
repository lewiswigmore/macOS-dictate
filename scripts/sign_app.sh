#!/usr/bin/env bash
# Code-sign dictate.app with Developer ID
#
# Requires:
#   - Apple Developer enrollment ($99/yr)
#   - Developer ID Application certificate installed in keychain
#   - Entitlements file at entitlements.plist
#
# Set DEVELOPER_ID env var to your certificate name, e.g.:
#   export DEVELOPER_ID="Developer ID Application: Your Name (TEAMID)"

set -euo pipefail
cd "$(dirname "$0")/.."

APP="dist/dictate.app"
if [[ ! -d "$APP" ]]; then
  echo "$APP not found. Run ./scripts/build_app.sh first." >&2
  exit 1
fi

if [[ -z "${DEVELOPER_ID:-}" ]]; then
  echo "DEVELOPER_ID env var not set." >&2
  echo "Export your cert name first, e.g.:" >&2
  echo "  export DEVELOPER_ID=\"Developer ID Application: Your Name (TEAMID)\"" >&2
  exit 1
fi

ENTITLEMENTS="entitlements.plist"
if [[ ! -f "$ENTITLEMENTS" ]]; then
  echo "$ENTITLEMENTS not found. See docs/build-app.md for the template." >&2
  exit 1
fi

echo "Signing $APP with $DEVELOPER_ID..."
codesign --force --deep --options runtime --timestamp \
  --entitlements "$ENTITLEMENTS" \
  --sign "$DEVELOPER_ID" \
  "$APP"

echo "✓ Signed. Verify with: codesign --verify --deep --verbose=2 $APP"
echo "Next: ./scripts/notarize_app.sh"
