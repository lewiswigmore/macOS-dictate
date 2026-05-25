# First run

The first launch opens an onboarding wizard that checks the local setup before you start dictating.

## Wizard walkthrough

1. **Welcome and privacy summary** — confirms that local Whisper and Ollama are the default path and that OpenRouter is opt-in.
2. **Accessibility permission** — opens the relevant System Settings pane and waits for you to grant access.
3. **Microphone permission** — requests microphone access and verifies the selected input device.
4. **Input Monitoring permission** — guides you to enable hotkey and synthetic input support.
5. **Mic test** — records a short sample so you can confirm the meter moves and audio reaches the recorder.
6. **Backend reachability** — checks Ollama or the configured cleanup backend and records any fallback state.
7. **Vocab seeding** — points you at `config/vocab/` for code, work, personal, and project terms.
8. **Hotkey confirmation** — shows the current hold/tap/double-tap behavior and where to remap it.

!!! tip "Run diagnostics any time"
    If the wizard reports a problem, run `dictate doctor` after fixing permissions or backend setup.
