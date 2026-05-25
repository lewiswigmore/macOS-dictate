#!/usr/bin/env bash
# Notarize signed dictate.app and staple the ticket
#
# Requires:
#   - Signed .app from ./scripts/sign_app.sh
#   - App-specific password stored in keychain as profile "AC_PASSWORD":
#       xcrun notarytool store-credentials AC_PASSWORD \
#         --apple-id "you@example.com" --team-id "TEAMID"

set -euo pipefail
cd "$(dirname "$0")/.."

APP="dist/dictate.app"
ZIP="dist/dictate-submission.zip"

if [[ ! -d "$APP" ]]; then
  echo "$APP not found. Run build + sign first." >&2
  exit 1
fi

echo "Zipping for submission..."
ditto -c -k --keepParent "$APP" "$ZIP"

echo "Submitting to Apple notary service (may take 5-15 min)..."
xcrun notarytool submit "$ZIP" --keychain-profile AC_PASSWORD --wait

echo "Stapling ticket to $APP..."
xcrun stapler staple "$APP"

echo "✓ Notarized + stapled."
echo "Verify: xcrun stapler validate $APP && spctl -a -vvv -t install $APP"
