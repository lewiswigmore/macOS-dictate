# Recipes

Concrete, copy-pasteable setups for things people actually use dictate for.
If you have a recipe worth sharing, [open a discussion](https://github.com/lewiswigmore/macOS-dictate/discussions)
or send a PR to this page.

## Dictating Slack messages with smart punctuation, no LLM

The default config already does this. Hold your hotkey, talk, release.
You get raw Whisper output plus rule-based punctuation, nothing leaves
your machine after the first-run model download. If you want a friendlier
tone, enable cleanup but pick a small local model so latency stays under
a second:

```yaml
# config/cleanup.yaml
enabled: true
backend: ollama
model: llama3.2:3b
preset_overrides:
  chat:
    style: casual
    max_tokens: 200
```

## Dictating Python or TypeScript

Switch your `code` preset to code-grammar mode so spoken keywords stay as
keywords:

```yaml
# config/presets.yaml
code:
  vocab: code
  code_grammar: true
  cleanup: false        # don't let an LLM rewrite source
  voice_commands: true  # "open paren", "new line", "delete that"
```

Then add the apps you write code in to the preset's `apps` list (VS Code,
Cursor, JetBrains IDEs, Terminal). See [code dictation](code-dictation.md)
for the full grammar.

## Dictating into Obsidian / iA Writer (prose)

```yaml
# config/presets.yaml
prose:
  vocab: prose
  code_grammar: false
  cleanup: true
  style: clean
  apps: ["md.obsidian", "pro.writer.mac"]
```

Cleanup here removes filler words ("um", "like", "you know") and fixes
punctuation without changing meaning. Compare a few utterances in the
[WebUI history](webui.md) to find a style you trust.

## Triggering dictate from Raycast

dictate ships with a Raycast extension under `raycast/`. Once installed,
bind "Start dictation" to a global Raycast hotkey if you'd rather drive
it from there than the menu-bar hotkey. See the
[Raycast guide](raycast.md).

## Triggering dictate from a Stream Deck / Keyboard Maestro

Use the [URL scheme](url-scheme.md):

```
open "dictate://start?preset=code"
open "dictate://stop"
open "dictate://toggle"
```

Any tool that can shell out or open a URL can drive dictate.

## Per-project vocab (e.g. internal acronyms)

Drop a `.dictate-vocab` file in your project root:

```
Kubernetes
GraphQL
OAuth
acme-corp
WigmoreNet
```

dictate's context detector picks it up when the frontmost app's working
directory is inside that project. See [per-app vocab](vocab.md) for the
matching rules.

## Redacting secrets before they reach a cloud LLM

If you ever turn on OpenRouter, the redactor scrubs API keys, AWS keys,
JWTs and GitHub tokens *before* the request leaves your machine. To add
your own pattern (e.g. an internal token format):

```yaml
# config/redact.yaml
patterns:
  - name: acme-internal-token
    regex: 'acme_[a-zA-Z0-9]{32}'
    replacement: '[REDACTED:acme-token]'
```

Reload the config from the [WebUI](webui.md) → Settings → "Reload" and
the new rule is live without restarting.

## Health-checking everything in one go

```bash
dictate doctor
```

Prints model status, permissions status, backend reachability (Ollama
ping, OpenRouter ping if configured), and audio device list. Run this
first whenever something's not working.
