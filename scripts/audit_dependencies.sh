#!/usr/bin/env bash
set -Eeuo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

requirements="$(mktemp)"
trap 'rm -f "$requirements"' EXIT

# Audit the exact runtime and development versions, without resolving fresh dependencies
# or looking up the local project on PyPI. Keep the lockfile's integrity hashes.
uv export --frozen --all-extras --no-emit-project \
  --format requirements-txt --output-file "$requirements" >/dev/null
uv run --frozen pip-audit --strict --disable-pip --require-hashes \
  --requirement "$requirements" "$@"
