# Pre-launch checklist

## Code

- [ ] `python3 -m pytest -q` passes
- [ ] `python3 -m ruff check .` clean
- [ ] `python3 -m ruff format --check .` clean
- [ ] No `breakpoint()` / `pdb.set_trace()` / `print()` debug statements
- [ ] No hardcoded user paths (`/Users/<name>` outside tests using `__file__`)
- [ ] No personal data in `config/vocab/*.txt` (only generic templates)
- [ ] `history.jsonl`, `user_prefs.yaml`, `.onboarded`, `logs/*.log` removed

## Documentation

- [ ] README.md is accurate and free of TODOs
- [ ] ROADMAP.md reflects current direction
- [ ] CHANGELOG.md has a v0.1.0 entry
- [ ] FAQ.md answers cover main user questions
- [ ] SECURITY.md uses GitHub Security Advisories
- [ ] CONTRIBUTING.md describes setup + test workflow
- [ ] CODE_OF_CONDUCT.md routes through GitHub flows
- [ ] No placeholder emails (`@dictate.app` etc.)
- [ ] All GitHub URLs point at correct org (`lewiswigmore/dictate`)
- [ ] `THREAT_MODEL.md`, `THIRD_PARTY_NOTICES.md`, `docs/architecture.md` complete

## Build / CI

- [ ] `pyproject.toml` version is correct (e.g. 0.1.0)
- [ ] `pyproject.toml` URLs are correct
- [ ] `[project.scripts]` entries work (`dictate`, `dictate-web`)
- [ ] CI workflow on `.github/workflows/ci.yml` runs ruff + pytest on py3.11+3.12
- [ ] Dependabot enabled (`.github/dependabot.yml`)
- [ ] Pre-commit config present (`.pre-commit-config.yaml`)
- [ ] CODEOWNERS set

## Repository hygiene

- [ ] `.gitignore` excludes runtime artifacts
- [ ] Single root commit (`git log --oneline` shows one entry)
- [ ] Working tree clean (`git status`)
- [ ] Commit message has Co-authored-by trailer where appropriate

## Privacy

- [ ] Default config uses local backends (no cloud by default)
- [ ] No telemetry, no analytics, no remote logging
- [ ] WebUI binds 127.0.0.1 only
- [ ] WebUI has CSP / nosniff / referrer-policy headers
- [ ] OpenRouter is opt-in via explicit env var

## After push

- [ ] Create a `v0.1.0` git tag and GitHub release
- [ ] Enable GitHub Security Advisories on the repo
- [ ] Enable Discussions for community Q&A
- [ ] Add repo description + topics on GitHub (`macos`, `dictation`, `whisper`, `privacy`, `voice`, `local-first`)
- [ ] Add a social-preview image (optional)
- [ ] Announce on relevant communities (HN Show HN, /r/MacOS, Mastodon)
