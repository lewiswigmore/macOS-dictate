# WebUI

The private history WebUI lets you review dictated transcripts locally.

## Launch

```bash
dictate-web
```

or during development:

```bash
python -m dictate.webui
```

Open <http://127.0.0.1:47843>.

## What it shows

The WebUI includes:

- Transcript history from `history.jsonl`.
- Raw and cleaned text views.
- Search and filtering by app, preset, backend, and date.
- Star and delete actions.
- Purge and export flows for local history management.

## Port

The default port is `47843`. If the port is already in use, stop the other process or launch the WebUI from code with a different port.

## Security model

The WebUI is local-only:

- It binds to `127.0.0.1` by default.
- It refuses non-loopback hosts.
- Middleware rejects non-loopback clients.
- Security headers include a restrictive Content Security Policy, `X-Content-Type-Options: nosniff`, and `Referrer-Policy: no-referrer`.

There is intentionally no account system for v0.1 because the server is loopback-only.
