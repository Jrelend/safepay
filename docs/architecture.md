# SafePay architecture (Beta v0.1, Phase 0)

> SafePay is an escrow **simulation**. It never accepts, holds or transfers real
> money, and has no payment-provider integration.

## Monorepo layout

```
safepay/
├── apps/
│   ├── api/                 FastAPI + SQLAlchemy 2 + Alembic (Python 3.13, uv)
│   │   ├── app/
│   │   │   ├── api/         HTTP routers (health/readiness for now)
│   │   │   ├── core/        settings (pydantic-settings)
│   │   │   ├── db/          engine / session factory
│   │   │   ├── domain/      pure logic: money, deal state machine, ledger rules
│   │   │   └── models/      ORM models
│   │   ├── migrations/      Alembic (initial schema + DB safety triggers)
│   │   └── tests/           unit/ (no DB) and integration/ (real PostgreSQL)
│   └── web/                 Next.js 16 (App Router) + Tailwind CSS 4, Mongolian UI
├── docs/                    this documentation
├── compose.yaml             production-like stack (local + future VPS)
├── compose.dev.yaml         hot-reload override
└── .github/workflows/ci.yml
```

## Runtime components

```
 browser ──HTTPS──▶ [reverse proxy, VPS only] ──▶ web (Next.js, :3000)
                                                   │ server-side fetch
                                                   ▼
                                                 api (FastAPI, :8000) ──▶ db (PostgreSQL 17)
                                                   ▲
                                 migrate (one-shot: alembic upgrade head)
```

* **web** renders the UI only. It never talks to the database and never decides a
  deal's state; it shows what the API returns. API calls are made
  server-side (`API_INTERNAL_URL`), so the API does not need to be public.
* **api** is the single authority over deal state and the simulated ledger.
* **migrate** runs Alembic before `api` starts (`service_completed_successfully`),
  so the API never serves against an old schema. `/ready` also reports
  503 if the schema is not at the expected Alembic head.
* **db** is reachable only on the internal `backend` network.

## Data model

| Table | Purpose |
|---|---|
| `users` | Participant identity (E.164 phone, display name, status). |
| `deals` | Escrow agreement: title, `amount_mnt` (BIGINT > 0), `currency` = `MNT`, `status`, optimistic-lock `version`. |
| `deal_participants` | Exactly one BUYER and one SELLER per deal; a user cannot be both. |
| `ledger_accounts` | Chart of accounts: `SIMULATED_CASH` (asset), `USER_WALLET` / `DEAL_ESCROW` (liability), `FEE_REVENUE` (revenue). **No balance column.** |
| `ledger_transactions` | Journal header with a unique `idempotency_key`; optional `reverses_transaction_id` for corrections. Append-only. |
| `ledger_entries` | DEBIT/CREDIT lines, `amount_mnt` BIGINT > 0. Append-only. |
| `audit_events` | Who did what to which entity and when, with request ID and JSON details. Append-only. |

### Simulated double-entry ledger

All amounts are whole MNT stored in `BIGINT`. A balance is always
`SUM(entries)` in the account's normal direction (`app/domain/ledger.py`);
nothing ever "sets" a balance.

Planned postings (built in Phase 1 and later; see `docs/transaction-states.md`):

| Event | Debit | Credit |
|---|---|---|
| Buyer funds escrow (simulated) | `SIMULATED_CASH` | `DEAL_ESCROW(deal)` |
| Release to seller | `DEAL_ESCROW(deal)` | `USER_WALLET(seller)` (+ `FEE_REVENUE` if fees are introduced) |
| Refund to buyer | `DEAL_ESCROW(deal)` | `USER_WALLET(buyer)` |
| Correction | mirror of the original entries, linked via `reverses_transaction_id` | |

Invariant: a deal's escrow balance equals `amount_mnt` while the deal is in
`FUNDED`, `DELIVERED` or `DISPUTED`, and is `0` otherwise.

### Enforced by PostgreSQL (not only Python)

Defined in `migrations/versions/20261009_0001_initial_schema.py` and covered
by `tests/integration`:

1. `ledger_transactions`, `ledger_entries` and `audit_events` reject `UPDATE`,
   `DELETE` and `TRUNCATE`.
2. Deferred constraint triggers check at `COMMIT` that every ledger
   transaction has ≥ 2 entries on ≥ 2 accounts and that debits = credits.
3. Entries can only be added in the same DB transaction that created the
   journal header (a committed transaction is sealed).
4. CHECK constraints: positive amounts, `currency = 'MNT'`, known enum values,
   account purpose ↔ type, wallet ↔ owner, escrow ↔ deal.
5. Partial unique indexes: one wallet per user, one escrow account per deal,
   one of each system account.
6. A unique `idempotency_key` on ledger transactions.

### Atomicity and idempotency (Phase 1 design)

A state-changing request (for example *fund deal*) will run in **one** DB transaction:

1. `SELECT … FOR UPDATE` the deal row (and compare `version`).
2. `resolve_transition(status, action, actor)` rejects illegal transitions.
3. Insert the ledger transaction and the entries required by `transition.ledger_effect`,
   with `idempotency_key = "<deal_id>:<action>:<client Idempotency-Key>"`.
4. Update `deals.status` (this bumps the version).
5. Insert an `audit_events` row.
6. `COMMIT`; the DB triggers validate the ledger again.

A retried request with the same `Idempotency-Key` hits the unique constraint
and returns the original result instead of posting twice.

## Health endpoints

* `GET /health` is the liveness check; it does not access the DB.
* `GET /ready` checks that the DB is reachable (`SELECT 1` with a statement timeout) and
  that `alembic_version` equals the code's migration head. Otherwise it returns **503**.

Every API response carries `X-Request-ID`, `X-SafePay-Simulation: true` and
`Cache-Control: no-store`.

## Frontend

* `lang="mn"`, with Mongolian copy in `src/lib/i18n/mn.ts`. System fonts cover
  Mongolian Cyrillic (Ө, Ү) fully, so no font is downloaded at build time.
* Mobile-first: `max-w-md` column, sticky header, bottom navigation with
  safe-area padding, touch targets ≥ 48 px, light and dark themes.
* A permanent banner says that all payments are simulated.
* `formatMnt` handles BIGINT-sized amounts via `bigint` (no float rounding).
* A unit test parses the backend `DealStatus` enum and fails if the frontend
  status list drifts from it.
