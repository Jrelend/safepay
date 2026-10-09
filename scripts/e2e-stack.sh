#!/usr/bin/env bash
# Start a disposable SafePay stack for browser E2E tests (local or CI).
#
#   PGHOST/PGPORT/PGUSER/PGPASSWORD   a PostgreSQL *superuser* (bootstrap only)
#   E2E_DB                            database to (re)create, must end in _e2e
#
# Starts: public API :8000 (safepay_app), admin API :8001 (safepay_admin),
# web :3000 (next start). Logs go to $E2E_LOG_DIR. All payments are simulated.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
E2E_DB="${E2E_DB:-safepay_e2e}"
LOG_DIR="${E2E_LOG_DIR:-$ROOT/.e2e-logs}"
case "$E2E_DB" in *_e2e) ;; *) echo "E2E_DB must end in _e2e" >&2; exit 1 ;; esac
mkdir -p "$LOG_DIR"

MIGRATOR_PW="${E2E_MIGRATOR_PASSWORD:-e2e-migrator-password}"
APP_PW="${E2E_APP_PASSWORD:-e2e-app-password}"
SYSTEM_PW="${E2E_SYSTEM_PASSWORD:-e2e-system-password}"
ADMIN_PW="${E2E_ADMIN_PASSWORD:-e2e-admin-password}"
HOST="${PGHOST:-localhost}:${PGPORT:-5432}"

psql -d postgres -v ON_ERROR_STOP=1 -qc "DROP DATABASE IF EXISTS $E2E_DB WITH (FORCE)"
psql -d postgres -v ON_ERROR_STOP=1 -qc "CREATE DATABASE $E2E_DB"
psql -d "$E2E_DB" -v ON_ERROR_STOP=1 -q -v dbname="$E2E_DB" \
  -v migrator_password="$MIGRATOR_PW" -v app_password="$APP_PW" \
  -v system_password="$SYSTEM_PW" -v admin_password="$ADMIN_PW" \
  -f "$ROOT/infra/postgres/bootstrap-roles.sql" >/dev/null

export MIGRATION_DATABASE_URL="postgresql+psycopg://safepay_migrator:$MIGRATOR_PW@$HOST/$E2E_DB"
cd "$ROOT/apps/api"
uv run alembic upgrade head

common=(APP_ENV=test DEV_MAILBOX_ENABLED=true PUBLIC_WEB_URL=http://localhost:3000
        'CORS_ALLOWED_ORIGINS=["http://localhost:3000"]' TRUST_PROXY_HEADERS=true)
env "${common[@]}" API_MODE=public \
  DATABASE_URL="postgresql+psycopg://safepay_app:$APP_PW@$HOST/$E2E_DB" \
  nohup uv run uvicorn app.main:app --port 8000 >"$LOG_DIR/api.log" 2>&1 &
env "${common[@]}" API_MODE=admin DEV_MAILBOX_ENABLED=false \
  DATABASE_URL="postgresql+psycopg://safepay_admin:$ADMIN_PW@$HOST/$E2E_DB" \
  nohup uv run uvicorn app.main:app --port 8001 >"$LOG_DIR/admin-api.log" 2>&1 &

cd "$ROOT/apps/web"
API_INTERNAL_URL=http://127.0.0.1:8000 ADMIN_API_INTERNAL_URL=http://127.0.0.1:8001 PORT=3000 \
  nohup npx next start >"$LOG_DIR/web.log" 2>&1 &

for url in http://127.0.0.1:8000/ready http://127.0.0.1:8001/ready http://127.0.0.1:3000/; do
  curl -fsS --retry 40 --retry-delay 1 --retry-all-errors -o /dev/null "$url"
done
echo "E2E stack ready (db=$E2E_DB). Admin grants: MIGRATION_DATABASE_URL=$MIGRATION_DATABASE_URL"
