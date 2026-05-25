<!-- Mirror of ../ROADMAP.md - update both when changing -->

# Roadmap

Public roadmap, dated 2026.

## v0.1 — Current

Public OSS release:

- Privacy-first defaults
- Ollama + OpenRouter backends
- Local WebUI history viewer
- Vocab presets
- Voice commands
- MLX Whisper backend for Apple Silicon — shipped opt-in

## v0.2 — Integrations

- Raycast extension
- AppleScript dictionary (activates when packaged as `.app`)
- URL scheme handler (`dictate://`)

Out of scope: native Shortcuts.app App Intents. Those require a Swift binary
and an Xcode project, which conflicts with dictate's lightweight, pure-Python
design. The URL scheme + AppleScript dictionary cover the same use cases.

## v0.3 — ASR depth

- Streaming partial inserts
- Code-grammar mode
- Replacement dictionary layer

## v0.4 — Polish

- App icon + DMG packaging
- Sparkle auto-updates
- Homebrew tap
- Sound + haptic feedback
- Dark-mode HUD

## Beyond

- Meeting transcription mode
- Speaker diarization
- Plugin architecture
- Vocab sync across machines
- Real-time captioning overlay

This roadmap is aspirational. Priorities shift based on contributor interest and user feedback. File issues to weigh in.
