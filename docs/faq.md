<!-- Mirror of ../FAQ.md - update both when changing -->

# FAQ

Last updated: 2026-05-25

## Is dictate sending my voice anywhere?

No. By default everything runs locally: Whisper handles speech recognition, and Ollama handles cleanup. OpenRouter is opt-in only.

## Why macOS only?

The hotkey, accessibility, and synthetic input APIs dictate relies on are macOS-specific. A Linux port is theoretically possible but is not in scope for v0.1.

## What's the difference between dictate and macOS built-in Dictation?

Built-in Dictation requires holding fn or saying "Hey Siri", can send audio to Apple servers on older Macs, and does not offer developer-grade controls. dictate is hotkey-driven, runs locally by default, and supports per-app vocab, voice commands, redaction, and history review.

## How accurate is it?

Accuracy depends on the Whisper model. `tiny.en` is fast but error-prone, `small.en` is the default good tradeoff, and `medium.en` is more accurate but slower; run `dictate doctor` to see what's loaded.

## How do I use MLX for faster transcription on Apple Silicon?

Install the optional backend with `pip install mlx-whisper`, then set `asr.backend: mlx` in `config/settings.yaml` or your user prefs. The default MLX model is `mlx-community/whisper-small.en-mlx`; override it with `asr.mlx.model` if you want another model from `mlx-community` on Hugging Face.

## Can I dictate code?

Yes. The `code` preset includes developer vocabulary, and you can dictate replacements like "snake case my var"; this is currently LLM-cleaned, with deterministic code grammar planned for v0.3 in the ROADMAP.

## Where's my data stored?

Config lives in `~/.config/dictate/`, transcripts are stored in `<repo>/history.jsonl`, and model weights live under `~/.cache/huggingface/`. Nothing else is stored by dictate.

## How do I delete history?

Remove `history.jsonl` from the repo directory, or use the WebUI delete button via `dictate-web`.

## Why isn't there an app icon / DMG / Homebrew tap?

They are on the roadmap for v0.4. v0.1 is a clean OSS release; distribution polish comes next.

## Can I contribute?

Yes. See [CONTRIBUTING.md](https://github.com/lewiswigmore/macOS-dictate/blob/main/CONTRIBUTING.md) for the contribution workflow.

## How do I report a security issue?

Use GitHub Security Advisories. See [SECURITY.md](https://github.com/lewiswigmore/macOS-dictate/blob/main/SECURITY.md) for details.

## What if Ollama is down?

dictate falls back to raw, unedited ASR output automatically after 3 consecutive failures.

## Does it work with Slack/Notion/VSCode/etc?

Mostly yes. See [ROADMAP.md](roadmap.md) for documented edge cases per app.
