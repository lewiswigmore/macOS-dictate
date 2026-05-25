# Governance

dictate is a small, opinionated, privacy-first project. This document explains
who decides what, how changes get in, and how to participate.

## Roles

- **Maintainer** — currently [@lewiswigmore](https://github.com/lewiswigmore).
  Owns the roadmap, reviews all PRs, makes release decisions, and handles
  security advisories.
- **Contributor** — anyone opening an issue, discussion, or pull request.
- **Reviewer** — invited contributors with a track record of high-quality
  reviews. Reviewers may approve PRs but cannot bypass branch protection.

## Decision-making

- Routine changes (bug fixes, refactors, tests, docs): a maintainer review
  is sufficient.
- User-visible behavior changes, new dependencies, or anything that touches
  the privacy or security posture: open a discussion or issue first to agree
  on the approach, then submit a PR linking it.
- The maintainer has the final word on scope and direction. Project values:
  privacy first, no telemetry, no required network calls, native macOS feel.

## Pull request workflow

1. Fork and create a focused branch (`feat/...`, `fix/...`, `docs/...`).
2. Open a PR against `main`. The PR template is required.
3. CI must be green: `ruff`, `pytest`, `bandit`, `pip-audit`, CodeQL.
4. At least **one maintainer approval** is required to merge.
5. Direct pushes to `main` are blocked — even for the maintainer.
6. Merges are **squash-only**. Commit message should describe the change in
   imperative present tense (see `CONTRIBUTING.md`).

## Security issues

Never report security issues in public issues or PRs. Use the private
Security Advisory flow described in [`SECURITY.md`](SECURITY.md).

## Release process

1. Update `CHANGELOG.md` and bump version in `pyproject.toml`.
2. Open a PR titled `release: vX.Y.Z`.
3. After merge, tag the commit: `git tag vX.Y.Z && git push --tags`.
4. GitHub Actions publishes docs; release notes are drafted from the
   changelog.

## Code of conduct

All participation is governed by [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
