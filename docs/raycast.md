# Raycast

A Raycast extension lives in `raycast/` and controls dictate through the `dictate://` URL scheme.

## Commands

- **Toggle Recording** — start or stop a recording session.
- **Start Recording** — start a new recording session.
- **Stop Recording** — stop the current session.
- **Open History** — open the private WebUI.
- **Open Settings** — open dictate settings.

## Install for development

```bash
git clone https://github.com/lewiswigmore/macOS-dictate.git
cd dictate/raycast
npm install
npm run dev
```

Requirements:

- dictate installed locally.
- Raycast installed.
- During v0.1 development, invoke URLs manually with `python3 -m dictate "dictate://toggle"` if no packaged app is registered.

## Publish

Raycast publishing uses the extension manifest in `raycast/package.json`.

```bash
cd raycast
npm run lint
npm run build
npm run publish
```

The publish script runs:

```bash
npx @raycast/api@latest publish
```

The extension has no native dependencies; it dispatches macOS `open` commands for dictate URLs.
