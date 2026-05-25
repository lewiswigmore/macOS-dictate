# Contributing to dictate

Thanks for helping improve dictate. This project is a Python macOS menu-bar app for privacy-first, self-hosted voice typing.

## Development setup

```sh
./install.sh
source .venv/bin/activate
pytest
ruff check .
```

Use `AGENTS.md` as the source of truth for architecture, module boundaries, code style, and testing conventions.

## Pull request process

1. Fork the repository.
2. Create a focused branch for your change.
3. Make the smallest complete change that solves the problem.
4. Run `ruff check .` and `pytest` before opening a PR.
5. Link related issues and describe user-visible changes.
6. Update docs when behavior, setup, or conventions change.

Mic-, Accessibility-, and Input Monitoring-dependent tests are skipped in CI because GitHub-hosted runners do not provide real devices or user-granted macOS permissions.

## Commit style

Use imperative present tense:

- `Add Ollama health check`
- `Fix recorder hot-plug handling`
- `docs: clarify permission setup`

A short scope prefix is optional when it improves clarity.

## Areas needing help

- More ASR backend integrations
- Additional context presets for apps and workflows
- Linux and Windows ports; dictate is currently macOS-only
