#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Restore the staging database from a backup made by staging-backup.sh.
#   scripts/staging-restore.sh backups/daily/safepay-20261010T020000Z.dump [--yes]
# Encrypted backups (.age) need AGE_IDENTITY_FILE=/path/to/key.txt.
# This REPLACES the current database. Take a fresh backup first.
set -euo pipefail
. "$(dirname "$0")/staging-lib.sh"
load_env

file="${1:?usage: staging-restore.sh <backup-file> [--yes]}"
[[ -f "$file" ]] || { echo "no such file: $file" >&2; exit 1; }
if [[ -f "$file.sha256" ]]; then
  (cd "$(dirname "$file")" && sha256sum --check --status "$(basename "$file").sha256") \
    || { echo "checksum mismatch for $file; refusing" >&2; exit 1; }
fi

tmp=""
cleanup() { if [[ -n "$tmp" ]]; then rm -f "$tmp"; fi; }
trap cleanup EXIT
if [[ "$file" == *.age ]]; then
  : "${AGE_IDENTITY_FILE:?set AGE_IDENTITY_FILE to decrypt $file}"
  tmp="$(mktemp)"
  age -d -i "$AGE_IDENTITY_FILE" -o "$tmp" "$file"
  file="$tmp"
fi
dc exec -T db pg_restore --list < "$file" > /dev/null

if [[ "${2:-}" != "--yes" ]]; then
  read -r -p "Replace database '$POSTGRES_DB' with $1? Type 'restore' to continue: " answer
  [[ "$answer" == "restore" ]] || { echo "aborted"; exit 1; }
fi

echo "stopping application services..."
dc stop caddy web api admin-api worker >/dev/null 2>&1 || true

echo "recreating database $POSTGRES_DB..."
db_psql -d postgres -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\" WITH (FORCE)"
db_psql -d postgres -c "CREATE DATABASE \"$POSTGRES_DB\""
# Same role/ownership/privilege bootstrap as a fresh volume (idempotent).
db_psql -d "$POSTGRES_DB" -v dbname="$POSTGRES_DB" \
  -v migrator_password="$SAFEPAY_MIGRATOR_PASSWORD" -v app_password="$SAFEPAY_APP_PASSWORD" \
  -v system_password="$SAFEPAY_SYSTEM_PASSWORD" -v admin_password="$SAFEPAY_ADMIN_PASSWORD" \
  -f /safepay/bootstrap-roles.sql > /dev/null

echo "restoring (single transaction)..."
dc exec -T db pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  --exit-on-error --single-transaction < "$file"

version="$(db_psql -d "$POSTGRES_DB" -At -c 'SELECT version_num FROM alembic_version')"
owners="$(db_psql -d "$POSTGRES_DB" -At -c \
  "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tableowner <> 'safepay_migrator'")"
[[ "$owners" == "0" ]] || { echo "restore check failed: tables not owned by safepay_migrator" >&2; exit 1; }
echo "restored schema version $version"

if [[ "${RESTORE_SKIP_START:-0}" != "1" ]]; then
  echo "starting application services..."
  dc up -d >/dev/null
fi
echo "restore ok"
