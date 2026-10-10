# shellcheck shell=bash
# Shared helpers for the staging scripts (sourced, not executed).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${STAGING_ENV_FILE:-$ROOT/.env.staging}"
COMPOSE_FILE="${STAGING_COMPOSE_FILE:-$ROOT/compose.staging.yaml}"

load_env() {
  [[ -f "$ENV_FILE" ]] || { echo "missing $ENV_FILE (run scripts/staging-init-secrets.sh)" >&2; exit 1; }
  if grep -Eq '^[^#]*CHANGE_ME' "$ENV_FILE"; then
    echo "$ENV_FILE still contains CHANGE_ME placeholders; refusing" >&2; exit 1
  fi
  if [[ "$(stat -c %a "$ENV_FILE")" != "600" ]]; then
    echo "warning: $ENV_FILE should be chmod 600" >&2
  fi
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
  POSTGRES_USER="${POSTGRES_USER:-postgres}"
  POSTGRES_DB="${POSTGRES_DB:-safepay}"
  BACKUP_DIR="${BACKUP_DIR:-$ROOT/backups}"
  case "$BACKUP_DIR" in /*) ;; *) BACKUP_DIR="$ROOT/${BACKUP_DIR#./}" ;; esac
}

dc() {
  local extra=()
  # Optional extra compose file (tests only, e.g. to publish the DB port locally).
  [[ -n "${STAGING_COMPOSE_EXTRA:-}" ]] && extra=(-f "$STAGING_COMPOSE_EXTRA")
  docker compose --project-directory "$ROOT" -f "$COMPOSE_FILE" "${extra[@]}" \
    --env-file "$ENV_FILE" "$@"
}

db_psql() { dc exec -T db psql -U "$POSTGRES_USER" -v ON_ERROR_STOP=1 -X -q "$@"; }
