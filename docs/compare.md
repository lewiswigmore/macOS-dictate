# How dictate compares

A fair, factual look at the macOS dictation landscape as of 2026. If anything
here is wrong or out of date, please [open an issue](https://github.com/lewiswigmore/macOS-dictate/issues/new)
or send a PR — this page is meant to help people pick the right tool, not to
sell anything.

## At a glance

| | **dictate** | Apple Dictation | [MacWhisper](https://goodsnooze.gumroad.com/l/macwhisper) | [Superwhisper](https://superwhisper.com/) | [Wispr Flow](https://wisprflow.ai/) |
|---|---|---|---|---|---|
| **Licence** | MIT, open source | Proprietary | Proprietary | Proprietary | Proprietary |
| **Price** | Free | Free (bundled) | Free + paid tiers | Paid (subscription) | Paid (subscription) |
| **Runs offline** | ✅ default | ⚠️ "Enhanced" only | ✅ | ✅ | ❌ cloud |
| **Telemetry** | None | Apple analytics (opt-out) | None claimed | None claimed | Cloud by design |
| **ASR engine** | Whisper (faster-whisper) | Apple SFSpeech | Whisper | Whisper + others | Proprietary |
| **LLM cleanup** | Optional, local (Ollama) or BYO key (OpenRouter) | None | Optional, paid | Built-in | Built-in |
| **Hotkey modes** | Hold / tap / double-tap | Tap (fn) | Configurable | Configurable | Configurable |
| **Per-app vocab / presets** | ✅ | ❌ | Limited | ✅ | ✅ |
| **Voice commands in-utterance** | ✅ | ❌ | Limited | ✅ | ✅ |
| **Secret redaction before LLM** | ✅ | n/a | ❌ | ❌ | ❌ |
| **Auditable code** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Packaged `.app`** | ⏳ planned | ✅ (built-in) | ✅ | ✅ | ✅ |

## When to pick each one

**Pick Apple Dictation if** the built-in tool already does what you need.
It's free, it's there, and "Enhanced Dictation" runs locally on Apple Silicon.
For most casual users, this is the right answer.

**Pick MacWhisper if** you want a polished, native Mac app for *files*
(meeting recordings, podcasts, voice memos) and only occasional live
dictation. It's the strongest tool in that category.

**Pick Superwhisper or Wispr Flow if** you want a managed product with
support and you don't mind paying a subscription. Wispr Flow is the
slickest hotkey-dictation experience on the market right now — if your
threat model is fine with cloud transcription, it's hard to beat on UX.

**Pick dictate if** any of these matter to you:

- You want **the LLM cleanup pipeline disabled by default** and full control
  over which model touches your text.
- You want to **audit the code** that records your microphone, sends it to
  a model, and pastes the result. Every line is on GitHub.
- You want **secret redaction** (API keys, AWS keys, tokens) to happen
  *before* anything optional leaves your machine.
- You're a developer who wants **per-app vocab presets**, code-grammar
  mode, voice commands, and a scriptable URL scheme / Raycast / AppleScript
  surface.
- You're fine running it from source (or building your own `.app`).

## What dictate is honestly not great at (yet)

- **No signed `.app`.** Until a paid Apple Developer ID is in the picture,
  install is `git clone + ./install.sh`. Friendly for developers, friction
  for everyone else.
- **No long-form file transcription UX.** dictate is built for short,
  hotkey-triggered insertion. For "transcribe this 90-minute meeting",
  MacWhisper is a better tool.
- **No iOS / iPad story.** macOS only by design.
- **Setup involves macOS permissions** (Accessibility, Input Monitoring,
  Microphone). Required for any tool that types into other apps; dictate
  has a [permissions guide](permissions.md) and `dictate doctor` to help.

## Migration notes

Coming from **Wispr Flow** or **Superwhisper**? The closest equivalent to
their "AI rewriter" is dictate's optional cleanup step. It's off by default;
enable it in the [WebUI](webui.md) and pick a local Ollama model (e.g.
`llama3.2:3b`) or wire in an OpenRouter key. Per-app presets in dictate
correspond loosely to "modes" in those products — configure them via
[per-app vocab](vocab.md).
