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

`config/vocab/replacements.txt` runs after ASR and before cleanup. Use it for deterministic fixes that should always happen.

```text
from -> to
open ai -> OpenAI
vs code -> VS Code
```

Keep replacements small and obvious. Prefer vocab entries when you only need recognition bias.

## Project vocab

Add per-project terms under `config/vocab/projects/`:

```text
config/vocab/projects/my-repo.txt
```

Use one term per line. Project vocab is intended for repo names, internal package names, acronyms and domain-specific jargon. Do not publish private customer data or secrets in project vocab files.
