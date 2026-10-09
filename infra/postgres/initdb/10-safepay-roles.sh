#!/bin/sh
# Runs once, on a fresh PostgreSQL volume (docker-entrypoint-initdb.d).
set -eu
: "${SAFEPAY_MIGRATOR_PASSWORD:?SAFEPAY_MIGRATOR_PASSWORD must be set}"
: "${SAFEPAY_APP_PASSWORD:?SAFEPAY_APP_PASSWORD must be set}"
: "${SAFEPAY_SYSTEM_PASSWORD:?SAFEPAY_SYSTEM_PASSWORD must be set}"
: "${SAFEPAY_ADMIN_PASSWORD:?SAFEPAY_ADMIN_PASSWORD must be set}"

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v dbname="$POSTGRES_DB" \
  -v migrator_password="$SAFEPAY_MIGRATOR_PASSWORD" \
  -v app_password="$SAFEPAY_APP_PASSWORD" \
  -v system_password="$SAFEPAY_SYSTEM_PASSWORD" \
  -v admin_password="$SAFEPAY_ADMIN_PASSWORD" \
  -f /safepay/bootstrap-roles.sql
