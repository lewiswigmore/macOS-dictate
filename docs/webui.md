# WebUI

A built-in, **loopback-only** web app for reviewing your dictation history,
checking system health and toggling features, no account, no telemetry, no
cloud.

## Launch

The menu-bar app auto-starts the WebUI in the background. Use **Menu Bar →
Open WebUI…** to open it, or visit it directly:

<http://127.0.0.1:47843>

CLI alternatives:

```bash
dictate-web              # blocking, useful from another shell
python -m dictate.webui  # development
```

## Pages

### Dashboard (`/`)

The home surface. Shows everything you need at a glance:

- **KPI cards**: utterances today, characters dictated, average cleanup
  latency (last 24 h), total entries in history.
- **Sparkline**: 14-day daily-utterances trend.
- **Recent dictations**: last 6 entries with app + latency badges.
- **System health**: backend (Ollama/OpenRouter/raw), latency, configured
  cleanup model, fallback if substituted.
- **Suggestions**: actionable nudges (only ever shown when they apply),
  e.g. "no transcripts in 30 days", "history file world-readable".
- **Quick actions**: jump to history search, 30-day stats, settings, export.

### Stats (`/stats`)

Operational view. Designed for owners debugging latency or backend choice:

- 30-day **utterances per day** chart with hourly breakdown.
- **Latency percentiles** (p50/p90/p99) for ASR, cleanup and end-to-end.
- **Local-vs-cloud ratio** showing how much processing stayed on-device.
- Top apps, top presets, redactions caught, voice commands triggered.

### History (`/history`)

Full transcript browser with:

- Search across raw + cleaned text.
- Filters: app, preset, backend, date range.
- Per-entry detail: raw vs cleaned diff, learn-corrections list, redactions
  caught, metrics (ASR ms, cleanup ms, model used).
- **Bulk delete** and **"purge older than N days"** controls.
- **Export** as JSONL, CSV or Markdown.

### Settings (`/settings`)

One-click toggles for runtime behaviour. **Cleanup is OFF by default** for
privacy; flip it on whenever you want LLM polishing:

- **Cleanup pipeline**: on/off, backend (Ollama / OpenRouter / raw), model.
- **Privacy mode**: force everything through the local backend.
- **Redaction**: toggle and review regex rules.
- **Hotkey**: re-bind the trigger key.
- **History retention**: auto-purge after N days.

Checkboxes are intentionally **click-target restricted**: you have to click
the actual checkbox, not the row label, so you can't toggle something by
accident while scanning the page.

## Security model

- Binds to `127.0.0.1` only. Middleware rejects any client whose
  `request.client.host` is not loopback. **Do not put dictate behind a
  local reverse proxy that forwards remote traffic** because the WebUI
  would then see the proxy as `127.0.0.1` and allow the request. If you
  need remote access, wait for the token-protected remote mode tracked
  on the [Roadmap](roadmap.md) instead of fronting the loopback server.
- **Custom-header CSRF defence**: every mutating request must carry
  `X-Dictate-WebUI: 1`, blocking CSRF from third-party origins (which
  can't set custom headers cross-origin without an explicit CORS
  pre-flight, which the server denies).
- **Strict CSP** with `frame-ancestors 'none'`, `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.
- **Prompt-injection fence**: every cleanup call wraps user audio in a
  per-request DICTATION nonce so a transcript can't impersonate system
  instructions to the LLM.
- **Symlink-safe writes**: history-file chmod uses `follow_symlinks=False`
  and refuses to operate on symlinks.
- No auth in v0.1 because the server is loopback-only. A token-protected
  remote mode is on the [Roadmap](roadmap.md).

## Port

Default port is `47843`. If the port is already taken, stop the other
process or pass `--port` to `dictate-web`.
