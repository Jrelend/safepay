# SafePay — Beta v0.1

Mongolian peer-to-peer escrow **simulation** platform. A buyer and a seller agree
on a deal, and SafePay simulates escrow funding, delivery confirmation, refunds and
disputes.

> ⚠️ **No real money.** SafePay never accepts, holds or transfers actual funds
> and has no payment integration. All amounts are integer MNT in a simulated
> double-entry ledger.

| | |
|---|---|
| Frontend | Next.js 16, TypeScript, Tailwind CSS 4 (`apps/web`) |
| Backend | Python 3.13, FastAPI, SQLAlchemy 2, Alembic (`apps/api`) |
| Database | PostgreSQL 17 |
| Tooling | uv, Ruff, mypy, pytest, ESLint, Vitest, Docker Compose, GitHub Actions |

## Quick start (Docker)

```bash
cp .env.example .env          # change every *_PASSWORD for anything but local use
docker compose up --build     # web: http://localhost:3000
# services: db, migrate, api (safepay_app), admin-api (safepay_admin, internal only),
#           worker (safepay_system), web (serves the UI and the /api proxy)
# Local only: with DEV_MAILBOX_ENABLED=true, verification/reset links appear at
#   http://localhost:3000/dev/mailbox
# Make someone an admin (owner credential, audited):
# (asks for a separate ADMIN password, prints a TOTP secret once; sign in at /admin/login)
docker compose run --rm -it migrate python -m app.cli grant-admin you@example.com
# hot reload:
docker compose -f compose.yaml -f compose.dev.yaml up --build
```

## Without Docker

```bash
# API (needs PostgreSQL 17). Create the roles once, as a superuser:
psql -U postgres -d safepay -v dbname=safepay \
     -v migrator_password=... -v app_password=... -v system_password=... -v admin_password=... \
     -f infra/postgres/bootstrap-roles.sql
cd apps/api
uv sync
uv run alembic upgrade head        # uses MIGRATION_DATABASE_URL (safepay_migrator)
uv run uvicorn app.main:app --reload
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest                      # integration tests need TEST_DATABASE_URL (superuser, *_test DB)

# Web
cd apps/web
npm ci
npm run dev                        # http://localhost:3000
npm run lint && npm run typecheck && npm test && npm run build

# Browser E2E (Playwright) against a disposable stack (PG superuser via PG* env vars)
PGHOST=localhost PGUSER=postgres PGPASSWORD=... ./scripts/e2e-stack.sh
cd apps/web && PGHOST=localhost PGUSER=postgres PGPASSWORD=... \
  MIGRATION_DATABASE_URL=postgresql+psycopg://safepay_migrator:e2e-migrator-password@localhost:5432/safepay_e2e \
  npx playwright test             # E2E_SCREENSHOT_DIR=... saves screenshots
```

## Endpoints

* `GET /health`, `GET /ready`: liveness / readiness (not exposed through the web proxy)
* `/auth/*`, `/me/*`: registration, verification, login/logout, password reset/change, sessions, profile, notifications, simulated wallet
* `/deals*`, `/invites/*`: deals, invitations, actions (`Idempotency-Key` required), timeline, escrow postings
* `/disputes/*`: dispute details, statements, evidence files
* `/admin/*` (admin API only): overview, disputes, notes, decisions, users, audit

All state-changing requests need the session cookie, a matching `X-CSRF-Token` and an
allowed `Origin`.

## Documentation

* [Architecture](docs/ARCHITECTURE.md)
* [Transaction states](docs/transaction-states.md)
* [Security requirements and database security model](docs/SECURITY.md)
* [Development phases](docs/PHASES.md)
* [Beta v0.1 plan and continuation log](docs/BETA_PLAN.md)
* [Private staging: architecture, costs, deployment, backups](docs/STAGING.md)
* [Beta final security review](docs/security-review-beta.md)
* [Phase 1A security review](docs/security-review-phase-1a.md)
