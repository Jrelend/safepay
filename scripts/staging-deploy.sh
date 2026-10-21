#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Deploy a reviewed commit/tag to the staging VPS (run ON the server, as the deploy user).
#   scripts/staging-deploy.sh <git-ref>          e.g. v0.1.0-beta.2 or a full commit SHA
#   scripts/staging-deploy.sh <git-ref> --yes    no confirmation prompt
# Steps: preflight checks -> backup (if a database exists) -> check out <git-ref> ->
# build images tagged with the commit -> start -> wait for health -> smoke test.
# The previous commit and the pre-deploy backup are recorded in .deploy/history so
# scripts/staging-rollback.sh can go back. Nothing here touches DNS, the firewall or
# any cloud resource. Payments stay simulated (enforced by config and checked below).
#
# Everything runs inside main(): this script checks out another commit while running,
# and bash reads scripts lazily, so the whole body must be parsed before that happens.
set -euo pipefail

main() {
  . "$(dirname "$0")/staging-lib.sh"
  load_env
  local ref="${1:?usage: staging-deploy.sh <git-ref> [--yes]}" assume_yes="${2:-}"
  cd "$ROOT"

  # --- Preflight -------------------------------------------------------------------
  docker info >/dev/null 2>&1 || { echo "cannot reach the Docker daemon (is docker running? is $(id -un) in the docker group?)" >&2; exit 1; }
  [[ "$(stat -c %a "$ENV_FILE")" == "600" ]] || { echo "chmod 600 $ENV_FILE first" >&2; exit 1; }
  if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "tracked files are modified on the server; refusing (git status)" >&2; exit 1
  fi
  if dc config 2>/dev/null | grep -Eiq 'PAYMENT_MODE: *(live|real|production)'; then
    echo "a real payment mode is configured; refusing" >&2; exit 1
  fi
  if [[ "$CADDY_TLS" != "internal" ]]; then
    "$ROOT/scripts/staging-check-dns.sh"
  fi
  [[ -n "${BACKUP_AGE_RECIPIENT:-}" ]] || echo "WARNING: BACKUP_AGE_RECIPIENT is empty: backups (incl. admin TOTP secrets) are NOT encrypted" >&2
  if [[ "$SITE_ACCESS" == "public" ]]; then
    echo "NOTE: SITE_ACCESS=public: the web site is open without the basic-auth login (admin area and API host stay behind it)" >&2
  fi
  [[ "$ADMIN_ALLOWED_IPS" != "127.0.0.1/32" ]] || echo "note: ADMIN_ALLOWED_IPS is 127.0.0.1/32, so /admin is unreachable from outside" >&2

  git fetch --quiet --tags origin
  local target previous
  # Branch names resolve to the freshly fetched remote branch, not a stale local one.
  target="$(git rev-parse --verify --quiet "origin/$ref^{commit}" || git rev-parse --verify --quiet "$ref^{commit}")" \
    || { echo "unknown git ref: $ref" >&2; exit 1; }
  previous="$(git rev-parse HEAD)"
  # The commit being deployed must carry this tooling (smoke test, image tags, rollback).
  git cat-file -e "$target:scripts/staging-smoke.sh" 2>/dev/null \
    || { echo "$ref predates the deployment tooling (scripts/staging-smoke.sh); refusing" >&2; exit 1; }
  echo "deploy: ${previous:0:12} -> ${target:0:12} ($ref) to https://$STAGING_DOMAIN (site access: $SITE_ACCESS)"
  if [[ "$assume_yes" != "--yes" ]]; then
    read -r -p "Type 'deploy' to continue: " answer
    [[ "$answer" == "deploy" ]] || { echo "aborted"; exit 1; }
  fi

  # --- Backup (skipped on the very first deploy, when no database exists yet) ---------
  local backup="none" schema_before="none"
  if [[ "$(dc ps db --format '{{.Health}}' 2>/dev/null)" == "healthy" ]]; then
    schema_before="$(db_psql -d "$POSTGRES_DB" -At -c 'SELECT version_num FROM alembic_version' 2>/dev/null || echo none)"
    backup="$("$ROOT/scripts/staging-backup.sh" | sed -n 's/^backup ok: \([^ ]*\).*/\1/p')"
    [[ -n "$backup" ]] || { echo "backup failed; refusing to deploy" >&2; exit 1; }
    echo "pre-deploy backup: $backup (schema $schema_before)"
  fi

  # --- Check out, build, start ----------------------------------------------------------
  mkdir -p "$ROOT/.deploy"
  printf '%s\tfrom=%s\tto=%s\tref=%s\tbackup=%s\tschema_before=%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$previous" "$target" "$ref" "$backup" "$schema_before" \
    >> "$ROOT/.deploy/history"
  git -c advice.detachedHead=false checkout --quiet --detach "$target"

  export IMAGE_TAG="${target:0:12}"
  dc build --pull
  echo "$IMAGE_TAG" > "$ROOT/.deploy/image-tag"
  dc up -d --remove-orphans
  if ! "$ROOT/scripts/staging-wait.sh" 600 || ! "$ROOT/scripts/staging-smoke.sh"; then
    echo "DEPLOY FAILED for ${target:0:12}. Inspect: docker compose -f compose.staging.yaml --env-file .env.staging logs --tail 200" >&2
    echo "Roll back with: scripts/staging-rollback.sh" >&2
    exit 1
  fi
  echo "deploy ok: ${target:0:12} ($ref), schema $(db_psql -d "$POSTGRES_DB" -At -c 'SELECT version_num FROM alembic_version')"
}

main "$@"
