#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Roll the staging VPS back to the commit that was live before the last deploy.
#   scripts/staging-rollback.sh                  # previous commit from .deploy/history
#   scripts/staging-rollback.sh --to <git-ref>   # a specific earlier commit/tag
#   options: --restore <backup-file>  restore this backup (default: the pre-deploy backup,
#                                     used only when the database schema is newer than
#                                     the target code), --yes (no prompt)
# Migrations refuse to downgrade over data, so when the last deploy applied a migration
# the database is put back from the backup taken just before that deploy. Any data
# written after that backup is then lost; the script says so and asks first.
# Encrypted backups need AGE_IDENTITY_FILE=/path/to/age-key.txt in the environment.
#
# Everything runs inside main(): this script checks out another commit while running.
set -euo pipefail

main() {
  . "$(dirname "$0")/staging-lib.sh"
  load_env
  cd "$ROOT"
  local target_ref="" backup="" assume_yes=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --to) target_ref="${2:?--to needs a git ref}"; shift 2 ;;
      --restore) backup="${2:?--restore needs a backup file}"; shift 2 ;;
      --yes) assume_yes=1; shift ;;
      *) echo "unknown argument: $1" >&2; exit 1 ;;
    esac
  done

  local current target line=""
  current="$(git rev-parse HEAD)"
  [[ -f .deploy/history ]] && line="$(awk -F'\t' -v c="to=$current" '$3 == c' .deploy/history | tail -1)"
  field() { tr '\t' '\n' <<<"$line" | sed -n "s/^$1=//p"; }
  if [[ -n "$target_ref" ]]; then
    target="$(git rev-parse --verify --quiet "$target_ref^{commit}")" || { echo "unknown git ref: $target_ref" >&2; exit 1; }
  else
    [[ -n "$line" ]] || { echo "no deploy of ${current:0:12} in .deploy/history; use --to <ref>" >&2; exit 1; }
    target="$(field from)"
  fi
  [[ "$target" != "$current" ]] || { echo "already at ${target:0:12}" >&2; exit 1; }
  git cat-file -e "$target:scripts/staging-smoke.sh" 2>/dev/null \
    || { echo "${target:0:12} predates the deployment tooling; roll back by hand (docs/DEPLOY_DIGITALOCEAN.md)" >&2; exit 1; }

  # Is the live schema known to the target code? If not, the backup must be restored.
  local schema need_restore=0
  schema="$(db_psql -d "$POSTGRES_DB" -At -c 'SELECT version_num FROM alembic_version')"
  if ! git grep -q "^revision: str = \"$schema\"" "$target" -- apps/api/migrations/versions; then
    need_restore=1
    if [[ -z "$backup" ]]; then backup="$(field backup)"; fi
    [[ -n "$backup" && "$backup" != "none" && -f "$backup" ]] \
      || { echo "schema $schema is newer than ${target:0:12} and no usable backup is recorded; pass --restore <file>" >&2; exit 1; }
  elif [[ -n "$backup" ]]; then
    need_restore=1
  fi

  echo "rollback: ${current:0:12} -> ${target:0:12}"
  if (( need_restore )); then
    echo "  database will be REPLACED by $backup (schema now: $schema)"
    echo "  everything written after that backup is LOST (a safety backup is taken first)"
  else
    echo "  database kept as is (schema $schema is known to the target code)"
  fi
  if [[ -z "$assume_yes" ]]; then
    read -r -p "Type 'rollback' to continue: " answer
    [[ "$answer" == "rollback" ]] || { echo "aborted"; exit 1; }
  fi

  if (( need_restore )); then
    "$ROOT/scripts/staging-backup.sh"   # the state we are about to discard
  fi
  git -c advice.detachedHead=false checkout --quiet --detach "$target"
  export IMAGE_TAG="${target:0:12}"
  if docker image inspect "safepay-api:$IMAGE_TAG" "safepay-web:$IMAGE_TAG" >/dev/null 2>&1; then
    echo "reusing images $IMAGE_TAG"
  else
    dc build
  fi
  echo "$IMAGE_TAG" > "$ROOT/.deploy/image-tag"
  if (( need_restore )); then
    RESTORE_SKIP_START=1 "$ROOT/scripts/staging-restore.sh" "$backup" --yes
  fi
  dc up -d --remove-orphans
  "$ROOT/scripts/staging-wait.sh" 600
  "$ROOT/scripts/staging-smoke.sh"
  printf '%s\tfrom=%s\tto=%s\tref=rollback\tbackup=%s\tschema_before=%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$current" "$target" "${backup:-none}" "$schema" >> "$ROOT/.deploy/history"
  echo "rollback ok: ${target:0:12}"
}

main "$@"
