# GitHub repository setup

After `git push -u origin main`, configure these on the GitHub web UI:

## About panel (right sidebar of repo page)

- **Description:** Privacy-first macOS voice dictation. Local Whisper + Ollama, OpenRouter optional.
- **Website:** (empty for now, or future docs site URL)
- **Topics:** `macos`, `dictation`, `whisper`, `voice`, `privacy`, `local-first`, `accessibility`, `productivity`, `python`, `ollama`, `transcription`, `speech-to-text`
- **Include in home page:** ✓ Releases  ✓ Packages  ✗ Deployments  ✗ Environments

## Features (Settings → General → Features)

- ✓ Issues
- ✓ Discussions (this enables the templates from `.github/DISCUSSION_TEMPLATE/`)
- ✓ Projects (optional — use for the public roadmap)
- ✗ Wikis (we use `docs/` instead)
- ✗ Sponsorships (enable when funding ready, then uncomment `.github/FUNDING.yml`)

## Security (Settings → Code security and analysis)

- ✓ Private vulnerability reporting (drives `SECURITY.md` advisory flow)
- ✓ Dependabot alerts
- ✓ Dependabot security updates
- ✓ Dependabot version updates (already configured via `.github/dependabot.yml`)
- ✓ Secret scanning
- ✓ Push protection for secrets

## Branch protection (Settings → Branches → Add rule for `main`)

- ✓ Require pull request before merging (0 reviewers is OK for solo maintainer)
- ✓ Require status checks to pass — select the CI workflow jobs
- ✓ Require linear history
- ✓ Require conversation resolution before merging

## Initial labels (Settings → Labels — bulk update)

Recommended labels beyond defaults:
- `good-first-issue` (existing, keep)
- `help-wanted` (existing, keep)
- `roadmap` (new — for tracking v0.2+ items)
- `accessibility` (new)
- `privacy` (new)
- `macos-version-specific` (new)
- `needs-repro` (new)
- `wont-fix` (existing, keep)

## First release

After confirming CI passes on `main`:

1. Run `./scripts/release.sh 0.1.0` to bump version + tag.
2. `git push origin main` then `git push origin v0.1.0`.
3. Visit the Releases tab → "Draft a new release" → choose tag `v0.1.0`.
4. Title: `v0.1.0 — Initial release`. Body: paste the v0.1.0 section from CHANGELOG.md.
5. Publish release.
6. (Optional) Submit to communities: HN Show HN, /r/MacOS, /r/Python, /r/privacy, Mastodon.
