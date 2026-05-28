#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 TAG" >&2
  echo "Example: $0 v0.1.0" >&2
}

if [[ $# -ne 1 ]]; then
  usage
  exit 64
fi

TAG="$1"
if [[ "$TAG" != v* ]]; then
  TAG="v${TAG}"
fi

URL="https://github.com/lewiswigmore/macOS-dictate/archive/refs/tags/${TAG}.tar.gz"

echo "${URL}"
curl -L "${URL}" | shasum -a 256
