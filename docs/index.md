# dictate

> Privacy-first macOS voice dictation. Local Whisper + Ollama, OpenRouter optional.

!!! info "Status"
    v0.1.0 — initial public release. See [Roadmap](roadmap.md) for what's planned.

## Why dictate?

- **Local by default.** Audio never leaves your Mac. No telemetry, no cloud upload, no account.
- **Hotkey-driven.** Hold, tap, or double-tap your chosen key to record. Pasted directly into the focused app.
- **Developer-grade.** Per-app vocab presets, voice commands, code-grammar mode, secret redaction.
- **Open source.** MIT licensed. [Read the code](https://github.com/lewiswigmore/dictate).

## Quick start

```bash
git clone https://github.com/lewiswigmore/dictate.git ~/dictate
cd ~/dictate
./install.sh
dictate
```

See [Install](usage.md) for full setup, [Permissions](permissions.md) for macOS perms, and [Voice commands](voice-commands.md) for what you can say.

## What it isn't

- **Not a meeting transcriber** — built for short, hotkey-triggered insertion (though it could be extended).
- **Not a replacement for Apple's built-in Dictation** if you only need basic speech-to-text and trust their servers.
- **Not yet a polished consumer product** — v0.1 is a clean OSS release. App icon, DMG, and Homebrew distribution are on the [roadmap](roadmap.md).

## Architecture at a glance

```mermaid
flowchart LR
    Hotkey --> Recorder --> VAD --> Whisper --> Cleanup --> Typer --> Focused App
    Whisper --> History --> WebUI
```

See the full [architecture diagram](architecture.md).
