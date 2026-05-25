#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 VERSION" >&2
  echo "Example: $0 0.1.0" >&2
}

if [[ $# -ne 1 ]]; then
  usage
  exit 64
fi

VERSION="${1#v}"
TAG="v${VERSION}"
RELEASE_DATE="$(date +%F)"

if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9]+)*$ ]]; then
  echo "Invalid version: $1" >&2
  usage
  exit 64
fi

if [[ "$(git rev-parse --abbrev-ref HEAD)" != "main" ]]; then
  echo "Release must be run from the main branch." >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree must be clean before release." >&2
  git status --short >&2
  exit 1
fi

if git rev-parse "$TAG" >/dev/null 2>&1; then
  echo "Tag already exists: $TAG" >&2
  exit 1
fi

sed_in_place() {
  local expression="$1"
  local file="$2"

  if sed --version >/dev/null 2>&1; then
    sed -i.bak -E "$expression" "$file"
    rm -f "${file}.bak"
  else
    sed -i '' -E "$expression" "$file"
  fi
}

sed_in_place "s/^version = \"[^\"]+\"/version = \"${VERSION}\"/" pyproject.toml

python3 - "$VERSION" "$RELEASE_DATE" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

version = sys.argv[1]
release_date = sys.argv[2]
path = Path("CHANGELOG.md")
text = path.read_text()
release_heading = f"## [{version}] - {release_date}"

if release_heading in text:
    raise SystemExit(f"CHANGELOG.md already contains {release_heading}")

marker = "## [Unreleased]"
if marker not in text:
    raise SystemExit("CHANGELOG.md is missing an Unreleased section")

text = text.replace(marker, f"{marker}\n\n{release_heading}", 1)
path.write_text(text)
PY

git add pyproject.toml CHANGELOG.md
git commit -m "Release ${TAG}" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git tag -a "$TAG" -m "Release ${TAG}"

cat <<EOF
Release ${TAG} prepared.

Next steps:
  git push origin main
  git push origin ${TAG}
  Create GitHub release from tag ${TAG}
  curl -L https://github.com/lewiswigmore/dictate/archive/refs/tags/${TAG}.tar.gz | shasum -a 256
  Update Formula/dictate.rb with the tarball SHA256
  Push Formula/dictate.rb to lewiswigmore/homebrew-dictate
EOF
