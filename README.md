<p align="left"><picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/dictate-wordmark-dark.svg">
    <img src="assets/brand/dictate-wordmark-light.svg" alt="dictate" width="320" height="80"></picture>
</p>

# dictate

Privacy-first voice typing for macOS. Hold a hotkey, speak and the
transcript is pasted into the focused app. Speech recognition runs on
your Mac. Optional LLM cleanup runs locally through Ollama or remotely
through OpenRouter and is off by default.

[![CI](https://github.com/lewiswigmore/macOS-dictate/actions/workflows/ci.yml/badge.svg)](https://github.com/lewiswigmore/macOS-dictate/actions/workflows/ci.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/lewiswigmore/macOS-dictate/badge)](https://scorecard.dev/viewer/?uri=github.com/lewiswigmore/macOS-dictate)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Docs site: <https://lewiswigmore.github.io/macOS-dictate/>

## What you get

- Local Whisper ASR on the Mac with VAD-driven endpointing.
- Optional cleanup pipeline. Off by default. Toggle on in the WebUI when
  you want polishing.
- Two cleanup backends, both opt-in. Ollama for fully local LLM cleanup.
  OpenRouter for cloud cleanup when you want a bigger model.
- Hotkey state machine with hold, tap and double-tap actions.
- Per-app vocab presets (code, work, personal, projects) chosen by the
  frontmost app.
- Voice commands like `new line`, `scratch that` and `paste raw`.
- Secret redaction before any cloud call. Patterns in `config/redact.yaml`.
- Correction learning that captures your Cmd+Z edits as few-shot examples
  for future cleanup prompts.
- Loopback-only WebUI at `http://127.0.0.1:47843` with a dashboard,
  stats, history search and settings.
- Synthetic Cmd+V insertion with a single Cmd+Z undo and full Unicode.

## Install

```bash
git clone https://github.com/lewiswigmore/macOS-dictate.git ~/dictate
cd ~/dictate
./install.sh                  # python deps and CLI shim
./install.sh --with-ollama    # also installs Ollama and pulls a default model
./install.sh --autolaunch     # optional: start at login, restart on crash
./run.sh
```

No API keys are required. dictate is designed as a self-hosted tool: clone,
install, run. There is no marketplace listing, signed `.app`, or Homebrew
cask, by design.

First launch opens a wizard that walks through Accessibility, Microphone
and Input Monitoring permissions, runs a mic test, checks backend
reachability and seeds your vocab files.

## Hotkeys

| Action | Hotkey |
|---|---|
| Push to talk | Hold Cmd+H for more than 250 ms, release to insert |
| Toggle continuous dictation | Tap Cmd+H, tap again to stop |
| Cancel in-flight | Double-tap Cmd+H within 400 ms or press Esc |
| Pause Cmd+H override | Menu bar then *Pause Cmd+H Override* |

Remap via `config/settings.yaml` under `hotkey.{mods,key}` or the menu
bar's *Set Hotkey...* dialog.

## WebUI

The menu-bar app starts the WebUI in the background. Open it from the
menu bar or visit <http://127.0.0.1:47843>.

| Page | What it shows |
|---|---|
| Dashboard | KPI cards, 14-day sparkline, recent dictations, system health, actionable suggestions |
| Stats | 30-day usage chart, latency percentiles for ASR and cleanup, local-vs-cloud ratio, top apps and presets |
| History | Full transcript search, filters by app, preset, backend and date, bulk delete, export as JSONL or CSV or Markdown |
| Settings | Cleanup on/off, backend, model, privacy mode, redaction, hotkey, retention |

The server binds to `127.0.0.1` only. Middleware rejects non-loopback
clients. Mutating requests require a custom `X-Dictate-WebUI` header so
third-party origins cannot forge requests across origins. CSP locks
`frame-ancestors` to `none`.

## Backends

Cleanup ships disabled. Enable it in Settings and pick a backend.

| Backend | Where it runs | Setup |
|---|---|---|
| ollama | Local Mac | `brew install ollama && ollama pull qwen2.5:3b-instruct` |
| openrouter | OpenRouter cloud | `export OPENROUTER_API_KEY=...` then enable in Settings |
| raw | None, pass through ASR output | Always available, the default |

If the active backend is unhealthy for over 60 seconds, dictate falls
back through `cleanup.fallback_chain`. If every cleanup backend fails,
raw Whisper output is pasted. The menu-bar *Privacy Mode* toggle forces
`cleanup.privacy_backend` (default `ollama`), useful if you normally use
OpenRouter but want a fully local pass on demand.

```yaml
cleanup:
  enabled: false
  backend: ollama
  model: qwen2.5:3b-instruct
  fallback_chain: [ollama, raw]
```

## Voice commands

Say any of these as the entire utterance:

- `new line` or `new paragraph` or `tab`
- `scratch that` or `delete that` or `nevermind`
- `stop` or `cancel`
- `fix last` or `redo` to re-clean the previous transcript
- `paste raw` to bypass LLM cleanup for this utterance

Add more in `config/commands.yaml`.

## Context presets

Driven by the frontmost app's bundle ID (`config/app_map.yaml`):

- **code** preserves identifiers and literal symbols and skips sentence auto-cap
- **chat** is casual with minimal cleanup
- **prose** does full grammar, punctuation and paragraphs
- **default** fallback

## Selection as context

If text is selected when you press the hotkey, dictate treats the
utterance as a rewrite instruction. Select a paragraph in Mail, hold the
hotkey, say "make this more concise" and the selection is replaced.
Requires Accessibility permission and an app that exposes
`kAXSelectedTextAttribute` (most native and Chromium apps qualify, some
Electron apps do not).

## Custom vocabulary

One term per line in `config/vocab/{code,work,personal}.txt`. Per-project
vocab in `config/vocab/projects/<repo-name>.txt`. Vocab is passed to
Whisper as `initial_prompt` to bias recognition and to the cleanup LLM
as a verbatim preservation list.

## Automation

Wire dictate into Keyboard Maestro, Hammerspoon, Shortcuts.app and other
tools via the `dictate://` URL scheme:

```bash
open "dictate://record"
open "dictate://history"
```

The URL scheme requires a packaged `.app` bundle to register with macOS
(tracked in [issue #10](https://github.com/lewiswigmore/macOS-dictate/issues/10)).
During development, invoke URLs directly:

```bash
python3 -m dictate "dictate://toggle"
```

AppleScript terminology lives at `assets/dictate.sdef` and activates
when dictate ships as an `.app`. A Raycast extension lives in
[`raycast/`](./raycast/) with commands for toggle, start, stop, open
history and open settings.

## CLI

After install, a `dictate` shim is on your PATH:

```bash
dictate start      # launch in the background
dictate stop       # graceful shutdown, falls back to SIGKILL after 8 s
dictate restart    # stop then start
dictate status     # show pid and pidfile path
dictate doctor     # full diagnostics: permissions, audio, backends, models, conflicts
dictate --version  # version, Python and macOS info
dictate --dry-run  # validate config and imports without starting
```

The pidfile lives at `~/Library/Application Support/dictate/dictate.pid`
(override via `DICTATE_STATE_DIR`). Background logs go to
`~/Library/Application Support/dictate/dictate.log`.

## Security

dictate ships with a hardened supply chain and is local-by-default:

- All GitHub Actions pinned to commit SHAs, with a hardened-runner egress
  audit step.
- AI code review on every PR via sebastionAI.
- OSSF Scorecard published on every push.
- Bandit and pip-audit gate pull requests.
- Secret scanning and push protection enabled at the repo level.
- Branch protection requires code-owner review, dismisses stale reviews,
  requires last-push approval, requires linear history and applies to
  admins too.
- Symlink-aware file writes refuse to follow links and chmod with
  `follow_symlinks=False`.
- Per-request DICTATION prompt-injection fence wraps every cleanup call
  so a transcript cannot impersonate system instructions.

Report security issues through GitHub Security Advisories rather than
public issues. See [SECURITY.md](SECURITY.md) and
[THREAT_MODEL.md](THREAT_MODEL.md).

## Troubleshooting

- **Hotkey not detected.** Check Accessibility and Input Monitoring
  permissions, then restart the app.
- **Event tap stopped silently.** Handled automatically (auto-reenable
  on `kCGEventTapDisabledByTimeout`). Check logs if it persists.
- **Whisper hallucinates on silence.** VAD should prevent it. Raise
  `vad.threshold` if it still occurs.
- **Selection not replaced.** The focused app does not expose AX
  selection. dictate falls back to appending.
- **Cmd+V does not paste.** Likely a secure-input field. dictate falls
  back to per-character typing.
- **AirPods or mic switch breaks recording.** Handled via configuration
  change notification. Restart if it does not recover.
- **Ollama not reachable.** `brew services start ollama && ollama pull
  qwen2.5:3b-instruct`.

Menu bar then *Export Diagnostics* produces a tar of recent logs, the
last five transcripts (redacted), your config and system info. Logs
rotate at `~/dictate/logs/dictate.log`.

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.dictate.app.plist 2>/dev/null || true
rm ~/Library/LaunchAgents/com.dictate.app.plist 2>/dev/null || true
rm -rf ~/dictate
```

## Develop

```bash
source .venv/bin/activate
pytest               # unit and end-to-end tests
ruff check .
```

Benchmarks live in [`bench/`](./bench/README.md) for ASR throughput and
synthetic end-to-end latency. See [AGENTS.md](AGENTS.md) for project
conventions and [CONTRIBUTING.md](CONTRIBUTING.md) for the PR workflow.

## Documentation

- [Architecture](./docs/architecture.md)
- [FAQ](./FAQ.md)
- [Changelog](./CHANGELOG.md)
- [Threat model](./THREAT_MODEL.md)
- [Third-party notices](./THIRD_PARTY_NOTICES.md)
- [Roadmap](./ROADMAP.md)

## Contributing

Pull requests are welcome. The [roadmap tracker](https://github.com/lewiswigmore/macOS-dictate/issues/20)
links every open issue with full acceptance criteria. Items tagged
`good first issue` are friendly starting points. All PRs are reviewed
and require green CI plus a code-owner approval before merge.

## License

MIT. See [LICENSE](LICENSE).
