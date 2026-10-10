#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Wait until every long-running staging service is healthy (migrate must have exited 0).
#   scripts/staging-wait.sh [timeout-seconds]
set -euo pipefail
. "$(dirname "$0")/staging-lib.sh"
load_env
deadline=$(( $(date +%s) + ${1:-300} ))
while :; do
  migrate="$(dc ps -a migrate --format '{{.State}} {{.ExitCode}}' 2>/dev/null || true)"
  if [[ "$migrate" == exited* && "$migrate" != "exited 0" ]]; then
    echo "migrate failed: $migrate" >&2; dc logs migrate >&2; exit 1
  fi
  pending=()
  for svc in db api admin-api web caddy; do
    [[ "$(dc ps "$svc" --format '{{.Health}}' 2>/dev/null)" == "healthy" ]] || pending+=("$svc")
  done
  [[ "$(dc ps worker --format '{{.State}}' 2>/dev/null)" == "running" ]] || pending+=(worker)
  if [[ ${#pending[@]} -eq 0 && "$migrate" == "exited 0" ]]; then
    echo "staging stack healthy"; exit 0
  fi
  if (( $(date +%s) > deadline )); then
    echo "timed out waiting for: ${pending[*]} (migrate: $migrate)" >&2; dc ps -a >&2; exit 1
  fi
  sleep 3
done
