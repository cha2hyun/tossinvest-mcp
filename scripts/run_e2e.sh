#!/usr/bin/env bash
set -Eeuo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

export TOSSINVEST_E2E_IMAGE="${TOSSINVEST_E2E_IMAGE:-tossinvest-mcp:e2e}"
e2e_project="${COMPOSE_PROJECT_NAME:-tossinvest-mcp-e2e}"
compose=(
  docker compose
  --ansi never
  --project-name "$e2e_project"
  --file compose.e2e.yaml
)

cleanup() {
  "${compose[@]}" down --volumes --remove-orphans
}
trap cleanup EXIT INT TERM

docker build --tag "$TOSSINVEST_E2E_IMAGE" .
"${compose[@]}" up \
  --abort-on-container-exit \
  --exit-code-from e2e-runner \
  --force-recreate \
  e2e-runner
