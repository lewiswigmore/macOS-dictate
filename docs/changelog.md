<!-- Mirror of ../CHANGELOG.md - update both when changing -->

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-05-25

### Added

- Initial public release.
- Hotkey-driven recording (hold / tap / double-tap state machine).
- Streaming `faster-whisper` ASR with silero VAD.
- Local cleanup via Ollama (default) and opt-in cleanup via OpenRouter.
- Per-app vocab presets: code, work, personal, projects.
- Voice commands: `scratch that`, `new line`, `new paragraph`, `spell that …`.
- Replacement dictionary layer (`config/vocab/replacements.txt`).
- Regex-driven secret redaction layer.
- Synthetic Cmd+V insertion with always-restore clipboard.
- Secure-input guard (refuses to paste into password fields).
- Click-through HUD + rumps menubar with status badges.
- First-run onboarding wizard.
- `dictate doctor` diagnostic subcommand.
- `dictate --version` and `dictate --dry-run` CLI flags.
- `dictate://` URL scheme handler.
- AppleScript dictionary (`assets/dictate.sdef`).
- Loopback-only WebUI for reviewing history (`dictate-web`, default port `47843`).
  - Stable SHA-256 entry IDs.
  - CSP, nosniff, referrer-policy headers.
  - fcntl advisory file locking for concurrent writes.
  - Empty state, dark mode (prefers-color-scheme), mobile-responsive nav.
  - Keyboard shortcuts and a11y landmarks.
- macOS conflict detection (built-in Dictation, Voice Control, other dictation apps, hotkey interceptors).
- Runtime resilience: AVAudioEngine reset on sleep/wake; audio route-change rebuild; Ollama circuit breaker; disk-full callback; invalid-YAML recovery.

### Documentation

- README, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY (via GitHub Security Advisories), CHANGELOG, ROADMAP, FAQ.
- THREAT_MODEL and THIRD_PARTY_NOTICES.
- `docs/architecture.md` with Mermaid diagrams.
- `docs/pre-launch-checklist.md`.

### Tooling

- MIT license.
- CI on macos-14 with Python 3.11 + 3.12 (ruff + pytest + advisory pip-audit + bandit).
- `pyproject.toml` with hatchling build backend and `[project.scripts]` for `dictate` and `dictate-web`.
- `justfile`, `py.typed` (PEP 561), pre-commit config, CODEOWNERS, dependabot.

[Unreleased]: https://github.com/lewiswigmore/dictate/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/lewiswigmore/dictate/releases/tag/v0.1.0
