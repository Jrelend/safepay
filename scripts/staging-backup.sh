#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Back up the staging database (logical dump, custom format, compressed).
#   scripts/staging-backup.sh            # e.g. daily from cron/systemd timer
# Output: $BACKUP_DIR/daily/safepay-<UTC timestamp>.dump[.age] + .sha256
# Sunday backups are also copied to $BACKUP_DIR/weekly/.
# Retention: daily files older than BACKUP_RETENTION_DAYS (default 14) and weekly
# files older than BACKUP_WEEKLY_RETENTION_WEEKS (default 8) are deleted.
# Role passwords are not in the dump (they live in .env.staging): back that file up
# separately, encrypted, e.g. in your password manager.
set -euo pipefail
. "$(dirname "$0")/staging-lib.sh"
load_env
umask 077

ts="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/weekly"
out="$BACKUP_DIR/daily/safepay-$ts.dump"

dc exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --compress=9 \
  > "$out.partial"
# Prove the archive is readable before keeping it.
dc exec -T db pg_restore --list < "$out.partial" > /dev/null
mv "$out.partial" "$out"

if [[ -n "${BACKUP_AGE_RECIPIENT:-}" ]]; then
  command -v age >/dev/null || { echo "BACKUP_AGE_RECIPIENT set but 'age' is not installed" >&2; exit 1; }
  age -r "$BACKUP_AGE_RECIPIENT" -o "$out.age" "$out"
  rm -f "$out"
  out="$out.age"
fi
(cd "$(dirname "$out")" && sha256sum "$(basename "$out")" > "$(basename "$out").sha256")

if [[ "$(date -u +%u)" == "7" ]]; then
  cp -p "$out" "$out.sha256" "$BACKUP_DIR/weekly/"
fi

find "$BACKUP_DIR/daily" -type f -name 'safepay-*' -mtime "+${BACKUP_RETENTION_DAYS:-14}" -delete
find "$BACKUP_DIR/weekly" -type f -name 'safepay-*' \
  -mtime "+$(( ${BACKUP_WEEKLY_RETENTION_WEEKS:-8} * 7 ))" -delete

echo "backup ok: $out ($(du -h "$out" | cut -f1))"
