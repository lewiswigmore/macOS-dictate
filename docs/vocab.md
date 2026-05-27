# Per-app vocab

dictate chooses a preset from the frontmost app, then merges vocabulary files for that preset. Vocab terms bias Whisper through `initial_prompt` and tell the cleanup model which terms to preserve verbatim.

## Presets

Vocabulary lives in `config/vocab/`:

- `code.txt`: developer tools, languages, identifiers, protocols and symbols.
- `work.txt`: team names, product names, customer names and workplace jargon.
- `personal.txt`: names, places, acronyms and phrases you use outside work.

Each file uses one term per line. Lines beginning with `#` are comments.

```text
GitHub
TypeScript
PostgreSQL
snake_case
```

## Replacements

Two formats are supported. The legacy plain-text file `config/vocab/replacements.txt` keeps working for simple `from -> to` pairs:

```text
open ai -> OpenAI
vs code -> VS Code
```

The YAML format at `config/vocab/replacements.yaml` unlocks regex rules and case-sensitive matching:

```yaml
- pattern: kubernetic
  replacement: Kubernetes

- pattern: "next ?js"
  replacement: Next.js
  regex: true

- pattern: API
  replacement: API
  case_sensitive: true
```

Both files are merged on load, with later layers winning. Drop a `config/vocab/<preset>.replacements.yaml` next to the global file to add per-preset overrides (e.g. `code.replacements.yaml` applies only when the `code` vocab preset is active).

Replacements run after ASR and before LLM cleanup, so the cleanup pass sees corrected text. Literal patterns match whole words, longest-first. Keep rules small and obvious; prefer vocab entries when you only need recognition bias.

## Project vocab

Add per-project terms under `config/vocab/projects/`:

```text
config/vocab/projects/my-repo.txt
```

Use one term per line. Project vocab is intended for repo names, internal package names, acronyms and domain-specific jargon. Do not publish private customer data or secrets in project vocab files.
