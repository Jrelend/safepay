# SafePay architecture (Beta v0.1)

> SafePay is an escrow **simulation**. It never accepts, holds or transfers real
> money, and has no payment-provider integration.

## Monorepo layout

```
safepay/
├── apps/
│   ├── api/                 FastAPI + SQLAlchemy 2 + Alembic (Python 3.13, uv)
│   │   ├── app/
│   │   │   ├── api/         HTTP routers: auth, me, deals, disputes, admin, dev mailbox
│   │   │   ├── core/        settings (pydantic-settings)
│   │   │   ├── db/          engine / session factory, atomic() transaction helper
│   │   │   ├── domain/      pure logic: money, deal state machine, ledger rules
│   │   │   ├── models/      ORM models
│   │   │   ├── services/    accounts, deals, disputes, transitions, idempotency, rate limits
│   │   │   ├── worker.py    expiry + auto-release loop (safepay_system role)
│   │   │   └── cli.py       grant-admin / revoke-admin (owner credential)
│   │   ├── migrations/      0001 schema + ledger triggers, 0002 database security, 0003 accounts/deals/disputes
│   │   └── tests/           unit/ (no DB) and integration/ (real PostgreSQL)
│   └── web/                 Next.js 16 (App Router) + Tailwind CSS 4, Mongolian UI, /api proxy, Playwright e2e/
├── infra/postgres/          role bootstrap SQL + Docker initdb hook
├── scripts/e2e-stack.sh     disposable stack for browser E2E
├── docs/                    this documentation
├── compose.yaml             production-like stack (local + future VPS)
├── compose.dev.yaml         hot-reload override
└── .github/workflows/ci.yml
```

## Runtime components

```
 browser ──HTTPS──▶ [reverse proxy, VPS only] ──▶ web (Next.js, :3000)
                                                   │ /api/*        → api       (FastAPI, API_MODE=public)  ── safepay_app
                                                   │ /api/admin/*  → admin-api (FastAPI, API_MODE=admin)   ── safepay_admin
                                                   ▼
                                                 db (PostgreSQL 17) ◀── worker (python -m app.worker)     ── safepay_system
                                                   ▲
                                 migrate (one-shot: alembic upgrade head)          ── safepay_migrator
```

* **web** serves the UI and a same-origin **proxy** (`src/app/api/[...path]/route.ts`).
  The browser never talks to the API host, so session cookies are first-party
  (`SameSite=Lax`, `__Host-` when secure) and no CORS is needed. The proxy forwards an
  explicit header allow-list and routes `/api/admin/*` to the admin API only.
  Authenticated pages are client-rendered against the proxy; server components never
  read the session, so no user data enters the Next.js cache.
* **api** (public) is the authority over deals and the simulated ledger, as `safepay_app`.
* **admin-api** is the same image with `API_MODE=admin`: it mounts only `/admin/*` and
  auth-reading routes, runs as `safepay_admin`, and is not published on the host.
* **worker** runs a pass every `WORKER_INTERVAL_SECONDS`: expire deals idle for 7 days
  in PENDING_ACCEPTANCE/AWAITING_PAYMENT, auto-release DELIVERED deals after their
  inspection window, clean old rate-limit windows and outbox rows. The SQL function
  re-checks eligibility, so the worker cannot release early.
* **migrate** runs Alembic as `safepay_migrator` before the services start.
  `/ready` returns 503 if the schema is not at head or the role is too powerful.
* **db** is reachable only on the internal `backend` network.

### Request flow for a money action

1. The deal page opens a confirmation dialog; it creates one `Idempotency-Key` per
   dialog (double clicks and retries reuse it) and shows
   **"ТУРШИЛТЫН ТӨЛБӨР — БОДИТ МӨНГӨ БИШ"**.
2. `POST /api/deals/{id}/actions` → proxy → API: Origin check, session cookie,
   CSRF token, rate limit, participant check (404 otherwise).
3. `run_idempotent(scope="deal.transition:<user>")` → `safepay_transition_deal`,
   which locks the deal, derives the actor, checks the transition, posts the
   balanced ledger transaction, bumps the version, writes audit + notifications.
4. COMMIT runs the deferred checks (balanced, non-negative, idempotency complete).

## Data model

| Table | Purpose |
|---|---|
| `users` | Email (normalized, unique), Argon2id hash, verified-at, display name, optional phone, status. |
| `sessions`, `auth_tokens`, `email_outbox`, `rate_limits`, `admins` | Auth: hashed session/one-time tokens, simulated email, fixed-window limits, admin registry. |
| `disputes`, `dispute_evidence`, `notifications` | One dispute per deal; append-only statements/files/admin notes; per-user notifications written by the transition function. |
| `deals` | Escrow agreement: title, `amount_mnt` (BIGINT, 100 – 100 bn), `currency` = `MNT`, item type, delivery method, inspection days, hashed invite token, `status`, optimistic-lock `version`. |
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
* A permanent banner says that all payments are simulated; every screen showing or
  moving money adds the **"ТУРШИЛТЫН ТӨЛБӨР — БОДИТ МӨНГӨ БИШ"** notice.
* Unit tests also keep deal actions and API error codes (Mongolian messages) in sync
  with the backend source.
* Playwright E2E (`apps/web/e2e`, Pixel 7 viewport) drives the real stack: full escrow
  flow, double-click funding, dispute → admin refund, IDOR, CSRF/Origin, cookie flags,
  logout, open redirect.
* `formatMnt` handles BIGINT-sized amounts via `bigint` (no float rounding).
* A unit test parses the backend `DealStatus` enum and fails if the frontend
  status list drifts from it.
