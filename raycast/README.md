# dictate Raycast Extension

Control dictate from the Raycast launcher with five commands:

- **Toggle Recording** — start or stop a dictate recording session.
- **Start Recording** — start a new recording session.
- **Stop Recording** — stop the current recording session.
- **Open History** — open the private history WebUI.
- **Open Settings** — open dictate settings.

## Install

For development:

```bash
git clone https://github.com/lewiswigmore/macOS-dictate.git
cd dictate/raycast
npm install
npm run dev
```

Once published, install from Raycast or run:

```bash
npm run publish
```

## Requirements

- dictate must be installed.
- The packaged `.app` bundle must be registered for the `dictate://` URL scheme (v0.4 milestone).
- During v0.1 development, you can invoke URLs manually with `python3 -m dictate "dictate://toggle"`.

## Notes

The extension uses the macOS `open` shell command to dispatch `dictate://` URLs. It has no native dependencies and does not import the Python app.
