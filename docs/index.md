# dictate

Local voice typing for macOS. Hold a hotkey, speak, and dictate inserts the transcript into the focused app.

## Install

```bash
git clone https://github.com/lewiswigmore/macOS-dictate.git ~/dictate
cd ~/dictate
./install.sh
./run.sh
```

The first run asks for Accessibility, Microphone, and Input Monitoring permission. The menu-bar app then listens for the configured hotkey, `Cmd+H` by default.

## Use

- Hold the hotkey to dictate. Release it to finish.
- Tap it to start continuous dictation, then tap again to stop.
- Double-tap it or press Escape to cancel.
- Choose a different hotkey or microphone from the menu-bar app.

Speech recognition runs on your Mac. Cleanup is off by default. You can enable local Ollama cleanup or optional OpenRouter cleanup in settings.

The local WebUI is available at <http://127.0.0.1:47843>. It provides history, search, export, settings, and diagnostics.

## Help

Run these commands from the installation directory:

```bash
dictate doctor
dictate restart
dictate --dry-run
```

If the hotkey does not work, confirm Accessibility and Input Monitoring permission, then restart dictate. If audio is silent, confirm Microphone permission and select an input microphone from the menu-bar app.

## Privacy

History is stored locally at `~/dictate/history.jsonl` by default. The WebUI listens only on `127.0.0.1`. Optional cloud cleanup sends text to the configured provider only when you enable it.

For security reports, use [GitHub Security Advisories](https://github.com/lewiswigmore/macOS-dictate/security/advisories/new).
