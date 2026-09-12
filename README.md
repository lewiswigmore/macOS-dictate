# dictate

Local voice typing for macOS. Hold a hotkey, speak, and dictate inserts the transcript into the focused app.

[![CI](https://github.com/lewiswigmore/macOS-dictate/actions/workflows/ci.yml/badge.svg)](https://github.com/lewiswigmore/macOS-dictate/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Documentation: <https://lewiswigmore.github.io/macOS-dictate/>

## Install

```bash
git clone https://github.com/lewiswigmore/macOS-dictate.git ~/dictate
cd ~/dictate
./install.sh
./run.sh
```

The first run requests Accessibility, Microphone, and Input Monitoring permission.

## Use

- Hold `Cmd+H` to dictate, then release it to finish.
- Tap `Cmd+H` to start continuous dictation, then tap again to stop.
- Double-tap `Cmd+H` or press Escape to cancel.
- Choose a different hotkey or microphone from the menu-bar app.

Speech recognition runs locally. Cleanup is off by default. Enable local Ollama cleanup or optional OpenRouter cleanup only if you want it.

The WebUI runs locally at <http://127.0.0.1:47843> and provides history, search, export, settings, and diagnostics.

## Commands

```bash
dictate doctor
dictate restart
dictate --dry-run
```

## Help

If the hotkey does not work, confirm Accessibility and Input Monitoring permission, then restart dictate. If audio is silent, confirm Microphone permission and select an input microphone from the menu-bar app.

## Privacy and security

History is stored locally at `~/dictate/history.jsonl` by default. The WebUI listens only on `127.0.0.1`. Optional cloud cleanup sends text only when you enable it.

Report security issues through [GitHub Security Advisories](https://github.com/lewiswigmore/macOS-dictate/security/advisories/new).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. See [LICENSE](LICENSE).
