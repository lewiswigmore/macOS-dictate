# AGENTS.md — dictate

Conventions for AI coding sessions in this repo.

## Architecture
Pipeline: hotkey → recorder → vad → asr → (commands? | redact → cleanup) → typer → history. Threading: event tap + rumps/AppKit on main CFRunLoop; everything else on background threads with queue handoffs.

## Modules (single-responsibility)
- `dictate/__main__.py` — wiring, runloop, threading, lifecycle.
- `dictate/config.py` — YAML load + schema + accessors. All other modules read config via this.
- `dictate/logging_setup.py` — structured JSON logging. `get_logger(name)` returns a configured logger.
- `dictate/hotkey.py` — CGEventTap + Hold/Tap/DoubleTap state machine. Emits callbacks: `on_start`, `on_stop`, `on_cancel`.
- `dictate/recorder.py` — AVAudioEngine mic capture, hot-plug aware, VU level.
- `dictate/vad.py` — silero-vad streaming over the ring buffer.
- `dictate/asr.py` — faster-whisper streaming + final + confidence.
- `dictate/vocab.py` — per-context vocab merge (code/work/personal/projects).
- `dictate/context.py` — frontmost app → preset; AX selection read.
- `dictate/redact.py` — secret scanner (regex from `config/redact.yaml`).
- `dictate/commands.py` — voice command parser (regex from `config/commands.yaml`).
- `dictate/cleanup.py` — OpenAI-compatible chat-completions client. Backend-agnostic.
- `dictate/health.py` — backend ping + auto-fallback.
- `dictate/typer.py` — clipboard-paste insertion + restore.
- `dictate/learn.py` — capture corrections; provide few-shot examples to cleanup.
- `dictate/hud.py` — click-through NSPanel HUD.
- `dictate/menubar.py` — rumps status bar UI + toggles.
- `dictate/permissions.py` — Accessibility/Microphone/Input Monitoring checks + open Settings panes.
- `dictate/onboarding.py` — first-run wizard.
- `dictate/history.py` — JSONL append + reveal helpers.

## Conventions
- Python 3.11+. Type annotations everywhere (`from __future__ import annotations`).
- `httpx` for HTTP. Async where it composes naturally (cleanup); threads elsewhere.
- pyobjc imports: `from Foundation import …`, `from AppKit import …`, `from AVFoundation import …`, `import Quartz`. Avoid star imports.
- No global singletons; pass config + dependencies in constructors. Makes testing trivial.
- Logging: `log = get_logger(__name__)`. Per-utterance metrics dict logged at INFO at end of pipeline.
- Errors in background threads must not crash the main runloop; catch + log + notify menubar badge.
- Never block the main thread on I/O or model inference.

## Testing
- `pytest` in `tests/`. Mock pyobjc + httpx; unit tests must not require a mic, network, or models on disk.
- One end-to-end test pipes a fixture WAV through asr → stubbed cleanup → stubbed typer.

## Config
All behavior is config-driven via `config/*.yaml`. Defaults live in those files, not in code.

## Style
- ruff for lint (config in `pyproject.toml`).
- No comments unless the code is genuinely non-obvious (e.g. macOS quirks, AX edge cases).
- Function/method names are verbs. Module-level constants `SCREAMING_SNAKE`.

## Permissions reminders
- Synthetic Cmd+V via CGEvent requires **Accessibility** + **Input Monitoring**.
- AX selection read requires **Accessibility**.
- Mic requires **Microphone** + `NSMicrophoneUsageDescription` (set when packaged as `.app`).
