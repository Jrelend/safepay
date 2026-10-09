# SafePay architecture (Beta v0.1, Phase 0 + Phase 1A)

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
│   │   │   ├── db/          engine / session factory, atomic() transaction helper
│   │   │   ├── domain/      pure logic: money, deal state machine, ledger rules
│   │   │   ├── models/      ORM models
│   │   │   └── services/    idempotency + deal transitions (no HTTP endpoints yet)
│   │   ├── migrations/      Alembic: 0001 schema + ledger triggers, 0002 database security
│   │   └── tests/           unit/ (no DB) and integration/ (real PostgreSQL)
│   └── web/                 Next.js 16 (App Router) + Tailwind CSS 4, Mongolian UI
├── infra/postgres/          role bootstrap SQL + Docker initdb hook
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

 db roles:  migrate ── safepay_migrator (owns schema)   api ── safepay_app (least privilege)
```

* **web** renders the UI only. It never talks to the database and never decides a
  deal's state; it shows what the API returns. API calls are made
  server-side (`API_INTERNAL_URL`), so the API does not need to be public.
* **api** is the single authority over deal state and the simulated ledger.
* **migrate** runs Alembic as `safepay_migrator` before `api` starts
  (`service_completed_successfully`), so the API never serves against an old
  schema. `/ready` also reports 503 if the schema is not at the expected Alembic
  head, or if the API is connected as anything more powerful than `safepay_app`.
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
| `audit_events` | Who did what to which entity and when, with request ID and JSON details. Append-only; `occurred_at` set by the DB. |
| `deal_transitions` | The legal transitions (from, action, to, allowed actors, ledger effect), seeded by migration 0002. Read-only for the app; must equal `app/domain/deal_states.py` (tested). |
| `idempotency_records` | `(scope, key)` → request fingerprint and stored JSON result. Write-once after completion. |

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

### Phase 1A: database security

Migration `0002_database_security` (details and rationale in [SECURITY.md](SECURITY.md)):

1. **Role separation.** `safepay_migrator` owns everything. `safepay_app` has
   SELECT, narrow column-level INSERT/UPDATE grants, **no** write access to the
   ledger tables or to `deals.status`, and EXECUTE on one function only.
2. **`safepay_transition_deal()`** (SECURITY DEFINER) is the only way to change
   a deal's status or move simulated money. In one call it does the row lock →
   transition and actor check → escrow posting → version bump → audit event.
3. **No double funding, release or refund.** Deterministic escrow keys plus partial
   unique indexes, which also bind the schema owner.
4. **Guard triggers** on `deals`, `deal_participants`, `audit_events` and
   `idempotency_records`.

Escrow postings made by the function:

| Transition effect | Debit | Credit | Ledger key |
|---|---|---|---|
| HOLD_IN_ESCROW (FUND) | `SYSTEM:SIMULATED_CASH` | `ESCROW:<deal>` | `deal:<id>:ESCROW_HOLD` |
| RELEASE_TO_SELLER | `ESCROW:<deal>` | `WALLET:<seller>` | `deal:<id>:ESCROW_RELEASE` |
| REFUND_TO_BUYER | `ESCROW:<deal>` | `WALLET:<buyer>` | `deal:<id>:ESCROW_REFUND` |

Escrow and wallet accounts are created on first use, inside the function.

### Transaction pattern and idempotency

```
API request (Phase 1B)            ┌──────────────── one PostgreSQL transaction ─────────────────┐
  Idempotency-Key: k  ──▶ atomic ─┤ INSERT idempotency_records (scope,k) ON CONFLICT DO NOTHING │
                                  │   ├─ conflict → wait for other tx → same hash? replay : 409 │
                                  │   └─ claimed  → SELECT safepay_transition_deal(...)          │
                                  │                   FOR UPDATE · rules · ledger · audit        │
                                  │                 UPDATE idempotency_records SET response      │
                                  └──────────────── COMMIT (ledger re-validated) ───────────────┘
```

* `app/db/transactions.py`: `atomic(session)` gives exactly one transaction. It
  commits on success and rolls back on any exception, and refuses nesting.
  `lock_for_update()` wraps `SELECT … FOR UPDATE`.
* `app/services/idempotency.py`: `run_idempotent()`, which is reusable for any
  future operation.
* `app/services/deal_transitions.py`: `transition_deal()` combines idempotency
  with the DB function and maps SafePay SQLSTATEs (`SPD01`–`SPD05`) to typed
  exceptions. This is a service only; no HTTP endpoint exists yet.

## Health endpoints

* `GET /health` is the liveness check; it does not access the DB.
* `GET /ready` checks that the DB is reachable (`SELECT 1` with a statement timeout),
  that `alembic_version` equals the code's migration head, and that the API's DB role
  is least-privileged (not a superuser, no RLS bypass, owns no objects).
  Otherwise it returns **503**.

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
