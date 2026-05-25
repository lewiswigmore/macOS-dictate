# CLI reference

## `dictate`

Start the macOS menubar app and hotkey listener in the foreground.

```bash
dictate
```

Sample output is minimal in normal operation; status appears in the menubar and logs.

## `dictate start` / `stop` / `restart` / `status`

Manage a background dictate instance via a pidfile.

```bash
dictate start      # detach into the background
dictate stop       # SIGTERM, then SIGKILL after 8s if needed
dictate restart    # stop + start
dictate status     # show pid + pidfile path, exit 1 if not running
```

State lives at `~/Library/Application Support/dictate/` by default — override
with the `DICTATE_STATE_DIR` env var.

Background output is appended to `~/Library/Application Support/dictate/dictate.log`.

`dictate start --foreground` runs in the foreground while still managing the pidfile,
so `dictate stop` / `status` from another terminal work against it.

## `dictate doctor`

Print diagnostics for support and triage.

```bash
dictate doctor
```

Sample output:

```text
dictate doctor
==============

System
macOS: 14.5 (arm64)
Python: 3.12.3
Architecture: arm64
dictate version: 0.1.0

Permissions
✓ Accessibility: granted
✓ Microphone: granted
✓ Input Monitoring: granted
```

## `dictate --version`

Print version and platform information, then exit.

```bash
dictate --version
```

Sample output:

```text
dictate 0.1.0
Python 3.12.3 (arm64)
macOS 14.5
```

## `dictate --dry-run`

Validate config, imports, and required vocab files without starting the app.

```bash
dictate --dry-run
```

Sample output:

```text
dictate dry-run: OK
```

On failure, the command prints the exception and exits non-zero:

```text
dictate dry-run: FAILED: missing vocab file(s): code.txt
```

## URL arguments

The CLI also accepts startup URL arguments for development:

```bash
python3 -m dictate "dictate://toggle"
```
