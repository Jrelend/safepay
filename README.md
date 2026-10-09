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
cp .env.example .env          # set POSTGRES_PASSWORD
docker compose up --build     # web: http://localhost:3000  api: http://localhost:8000
# hot reload:
docker compose -f compose.yaml -f compose.dev.yaml up --build
```

## Without Docker

```bash
# API (needs PostgreSQL 17). Create the roles once, as a superuser:
psql -U postgres -d safepay -v dbname=safepay \
     -v migrator_password=... -v app_password=... -f infra/postgres/bootstrap-roles.sql
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
```

## Endpoints

* `GET /health`: liveness (no DB access)
* `GET /ready`: DB reachable and schema at the latest migration; otherwise 503

## Documentation

* [Architecture](docs/ARCHITECTURE.md)
* [Transaction states](docs/transaction-states.md)
* [Security requirements and database security model](docs/SECURITY.md)
* [Development phases](docs/PHASES.md)
