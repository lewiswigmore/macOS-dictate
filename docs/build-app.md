# Building dictate.app

This guide explains how to build dictate as a proper macOS .app bundle, sign it, and notarize it for distribution.

## Quick build (development, unsigned)

For local testing without signing:

```bash
pip install py2app
./scripts/build_app.sh --alias
open dist/dictate.app
```

Alias mode is much faster and symlinks back to your source — useful while iterating.
For a real bundle that's portable to other machines, drop `--alias`.

The unsigned .app will show a Gatekeeper warning on first launch on other machines.
Users can right-click → Open to bypass it, but for public distribution you'll want it signed and notarized.

## Production build (signed + notarized)

### One-time setup

1. Enroll in the Apple Developer Program ($99/year): https://developer.apple.com/programs/
2. Download a "Developer ID Application" certificate from the developer portal and install it in Keychain Access.
3. Generate an app-specific password at https://appleid.apple.com and store it:
   ```bash
   xcrun notarytool store-credentials AC_PASSWORD \
     --apple-id "you@example.com" --team-id "YOURTEAMID"
   ```

### Per-release build

```bash
# 1. Build
./scripts/build_app.sh --clean

# 2. Sign
export DEVELOPER_ID="Developer ID Application: Your Name (TEAMID)"
./scripts/sign_app.sh

# 3. Notarize + staple
./scripts/notarize_app.sh

# 4. Package for distribution
# Wrap into DMG using create-dmg:
#   brew install create-dmg
#   create-dmg --volname dictate --window-size 500 300 \
#     --icon dictate.app 125 150 --app-drop-link 375 150 \
#     dist/dictate-0.1.0.dmg dist/dictate.app
```

## Verifying the bundle

```bash
# Signature
codesign --verify --deep --verbose=2 dist/dictate.app

# Notarization (after stapling)
xcrun stapler validate dist/dictate.app

# Gatekeeper acceptance
spctl -a -vvv -t install dist/dictate.app
```

## Common gotchas

- **py2app + faster-whisper / onnxruntime**: these C-extension heavy deps sometimes fail to bundle. If you hit issues, try alias mode first to confirm the app boots, then experiment with the `includes`/`excludes` lists in setup_app.py.
- **pyobjc framework discovery**: py2app sometimes misses pyobjc framework subpackages. Add them explicitly to `includes` if you see import errors at runtime.
- **Code signing fails on nested binaries**: use `--deep` for the codesign call (already in sign_app.sh).
- **Notarization rejects**: read the JSON log via `xcrun notarytool log <submission-id> --keychain-profile AC_PASSWORD` — usually a missing entitlement.
- **App launches but hotkey doesn't work**: the bundle needs Accessibility + Input Monitoring permissions. Grant via System Settings → Privacy & Security.

## Roadmap

- v0.1 (current): manual build via this guide, unsigned for development.
- v0.4: CI workflow that produces a signed + notarized DMG on every tagged release.
