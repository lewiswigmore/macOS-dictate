# Permissions

dictate needs three macOS permissions to record audio and insert text into other apps.

!!! note "Screenshot placeholders"
    Add screenshots before v0.4 packaging: System Settings → Privacy & Security → Accessibility, Microphone, and Input Monitoring.

## Accessibility

Accessibility lets dictate observe the focused app, read selected text when available, and send paste keystrokes.

1. Open **System Settings**.
2. Go to **Privacy & Security** → **Accessibility**.
3. Click **+** or enable the existing entry for Terminal, your packaged `dictate.app`, or the Python runner you use during development.
4. Restart dictate after granting access.

If selection-as-context does not work, confirm the focused app exposes selected text through macOS Accessibility APIs.

## Microphone

Microphone permission lets the recorder capture your voice.

1. Open **System Settings**.
2. Go to **Privacy & Security** → **Microphone**.
3. Enable Terminal, your packaged `dictate.app`, or the Python runner.
4. Relaunch dictate and run the onboarding mic test or `dictate doctor`.

When packaged as an app, dictate includes `NSMicrophoneUsageDescription` so macOS can show the permission prompt.

## Input Monitoring

Input Monitoring is required for the global hotkey and synthetic keyboard events used for reliable insertion.

1. Open **System Settings**.
2. Go to **Privacy & Security** → **Input Monitoring**.
3. Enable Terminal, your packaged `dictate.app`, or the Python runner.
4. Quit and reopen dictate.

Without Input Monitoring, the hotkey may not fire or paste insertion may fail in focused apps.
