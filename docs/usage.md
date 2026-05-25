# Install

## Requirements

- macOS with Accessibility, Microphone, and Input Monitoring permissions available.
- Python 3.11 or newer.
- A local Whisper-compatible ASR setup installed by `./install.sh`.
- Ollama if you want the default local cleanup backend.
- Optional: an OpenRouter API key for opt-in cloud cleanup.

!!! tip "Privacy default"
    The default path is local: Whisper handles speech-to-text and Ollama handles cleanup. OpenRouter is only used when you explicitly configure it.

## Install via git

```bash
git clone https://github.com/lewiswigmore/macOS-dictate.git ~/dictate
cd ~/dictate
./install.sh --with-ollama
./install.sh --autolaunch   # optional: start at login and restart on crash
./run.sh
```

For a minimal install without Ollama management:

```bash
./install.sh
./run.sh
```

The `dictate` console script is installed by the Python package. During development, `./run.sh` starts the app from the checkout.

## Configure backends

Cleanup backends are configured in `config/settings.yaml` and `config/backends.yaml`.

```yaml
cleanup:
  backend: ollama
  model: qwen2.5:3b-instruct
  fallback_chain: [ollama, raw]
```

Use these common setups:

- **All local:** keep `backend: ollama` and `fallback_chain: [ollama, raw]`.
- **Cloud optional:** export `OPENROUTER_API_KEY`, switch the backend to `openrouter`, and keep Ollama or `raw` in the fallback chain.
- **Raw fallback:** if every cleanup backend is unhealthy, dictate pastes raw Whisper output rather than dropping your words.

## Verify with `dictate doctor`

Run diagnostics after install:

```bash
dictate doctor
```

`doctor` reports macOS version, Python version, permissions, audio devices, backend health, model availability, configuration paths, history count, and known conflicts such as other dictation tools or hotkey interceptors.

For a faster import/config check without starting the app:

```bash
dictate --dry-run
```
