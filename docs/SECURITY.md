# Security and financial-safety requirements

## Non-negotiable product rules

1. **Simulation only.** SafePay Beta never accepts, holds or transfers real
   money. It integrates no payment provider, bank, card or wallet API.
   `PAYMENTS_SIMULATION_ONLY` must be true, so the API refuses to start with any
   other value. Every response is tagged `X-SafePay-Simulation: true` and the UI
   shows a permanent banner.
2. **Integer MNT only.** Money is whole tögrög in `BIGINT`. There are no floats or
   decimals anywhere (Python `int`, TypeScript `bigint`). Column names end in
   `_mnt` (a test enforces this).
3. **Double-entry ledger, no stored balances.** Balances are derived from
   entries; a test fails if any column name contains `balance`.
4. **Immutable history.** Ledger and audit tables are append-only. Corrections
   are new reversing transactions.
5. **The backend is authoritative** for deal state, and PostgreSQL is the final
   authority: illegal transitions are rejected by the database itself.
6. **Atomic and idempotent** financial operations (see "Transaction pattern" and
   "Idempotency" below).

## Database security model (Phase 1A)

### Roles

| Role | Purpose | Attributes |
|---|---|---|
| `POSTGRES_USER` (superuser) | Initialises a fresh volume only. Nothing at runtime uses it. | superuser |
| `safepay_migrator` | Owns the `public` schema and **every** table, trigger and function. Used only by `alembic upgrade`. | `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS` |
| `safepay_app` | The API's runtime role. | `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT`, `CONNECTION LIMIT 50`; default `statement_timeout=15s`, `lock_timeout=5s`, `idle_in_transaction_session_timeout=30s` |

The timeouts are **defaults, not security controls**: any role may change its own
user-settable parameters (`SET`, or `ALTER ROLE safepay_app SET …`). They protect
against accidental long transactions, not against a holder of the app credential.

The roles are created by [`infra/postgres/bootstrap-roles.sql`](../infra/postgres/bootstrap-roles.sql).
It is idempotent and runs automatically on a fresh Compose volume through
`infra/postgres/initdb/10-safepay-roles.sh`. The script also:

- makes the migrator the owner of the database and of the `public` schema;
- removes `PUBLIC` access to the database and schema, so the app gets `CONNECT`
  and `USAGE` only, with no `CREATE` or `TEMPORARY`;
- revokes `EXECUTE` on future functions from `PUBLIC` by default. This uses the
  *global* form; migration 0002 repeats it, because a per-schema revoke of a
  globally granted default is silently ignored by PostgreSQL;
- revokes `PUBLIC` access to large-object creation (`lo_create`, `lo_creat`,
  `lo_from_bytea`), which the app never needs;
- revokes any role membership the app role might have.

Three gates enforce the role split:

1. `migrations/env.py` refuses to run any revision unless connected as
   `safepay_migrator`, and never as a superuser.
2. Migration 0002 repeats that check in SQL, and also refuses if any table is
   owned by another role.
3. `GET /ready` returns **503** if the API's connection is a superuser, can
   bypass RLS, or owns any object in `public`.

### What the application role can do

| Table | SELECT | INSERT | UPDATE | DELETE / TRUNCATE |
|---|---|---|---|---|
| `ledger_accounts`, `ledger_transactions`, `ledger_entries` | ✅ | ❌ | ❌ | ❌ |
| `audit_events` | ✅ | ✅ (timestamp forced by DB) | ❌ | ❌ |
| `deals` | ✅ | ✅ (DRAFT, version 1 only) | `title, description, amount_mnt, version, updated_at` — **not `status`** | ❌ |
| `deal_participants` | ✅ | ✅ (before acceptance) | `accepted_at` (once; DB sets the time) | ❌ |
| `users` | ✅ | ✅ | `display_name, status, updated_at` | ❌ |
| `idempotency_records` | ✅ | ✅ (claim only) | `response, completed_at` (once) | ❌ |
| `deal_transitions`, `alembic_version` | ✅ | ❌ | ❌ | ❌ |

The only function the app may execute is `safepay_transition_deal(...)`.

### Money moves only through `safepay_transition_deal`

This is a `SECURITY DEFINER` function owned by `safepay_migrator`, with
`search_path` pinned to `pg_catalog, public, pg_temp`. **Every** other SafePay
function, including the trigger functions, has the same pinned `search_path`.
This matters for the deferred constraint triggers: they fire at `COMMIT` with the
session's `search_path`, where `pg_temp` is searched first. The function contains
no dynamic SQL, and every input is a typed parameter that is compared, never
concatenated into SQL. In the caller's transaction it:

1. **locks** the deal row (`SELECT … FOR UPDATE`), so concurrent transitions
   of one deal are serialized;
2. optionally checks the caller's expected `version` (error `SPD02`);
3. looks up `(status, action)` in `deal_transitions` and checks the actor
   is allowed (error `SPD03`);
4. checks that a BUYER or SELLER actor **is that participant** of the deal, that SYSTEM
   has no user, and that ADMIN names an active user (error `SPD04`). A deal cannot
   leave DRAFT, except by being cancelled, until it has both a buyer and a seller;
5. posts the escrow ledger transaction, if the transition requires one. It
   checks the escrow balance first: empty before a hold, exactly the deal
   amount before a release or refund (error `SPD05`). It uses a
   **deterministic** idempotency key `deal:<id>:<kind>`;
6. updates `status` and bumps `version` by exactly 1;
7. writes an `audit_events` row.

If any step fails, PostgreSQL aborts the whole transaction, so there is no
partial financial operation.

### Defence in depth against double funding, release or refund

| Guard | Where |
|---|---|
| Row lock and legal-transition check (FUNDED cannot be funded again) | transition function |
| Escrow balance must be 0 before a hold and equal to the amount before settlement | transition function |
| `deal:<id>:ESCROW_HOLD` style key, which is unique | `ledger_transactions.idempotency_key` |
| One of each escrow kind per deal | partial unique index `uq_ledger_transactions_deal_escrow_kind` |
| At most one settlement (release **or** refund) per deal | partial unique index `uq_ledger_transactions_deal_settlement` |
| The app cannot write ledger tables at all | privileges |

The two indexes also bind the schema owner, so even a buggy future function cannot
settle a deal twice. Tests check this.

### Guard triggers (apply to every role, including the owner)

- **Ledger and audit:**
  - Append-only: UPDATE, DELETE and TRUNCATE are rejected.
  - Each ledger transaction must balance at COMMIT, and committed transactions
    are sealed (from Phase 0).
- **`audit_events.occurred_at`** is set to `clock_timestamp()` by a trigger;
  any client value is ignored.
- **`deals`:**
  - Created in DRAFT at version 1 only.
  - Identity columns (`id, reference, created_by_id, currency, created_at`) are
    immutable.
  - `amount_mnt` is frozen after DRAFT.
  - A status change must be an edge in `deal_transitions`.
  - Every update bumps `version` by exactly 1.
- **`deal_participants`:**
  - Can only be added while DRAFT or PENDING_ACCEPTANCE.
  - Immutable except for one `accepted_at`, which the DB stamps with server time.
- **`idempotency_records`:**
  - Must be claimed before they are completed.
  - Completed records are immutable.
- **`deal_transitions`:** cannot be updated or deleted.

### Design decision: where transition rules live

| Option | Verdict |
|---|---|
| Python only | Rejected: any bug or direct SQL with app credentials could set any status. |
| Trigger only (app may `UPDATE status`) | Not enough: a trigger can check the *edge* but cannot know the *action, actor or participant*, and cannot make the ledger posting atomic with the change. |
| **Stored procedure + privileges + trigger** (chosen) | The app has no UPDATE on `status`. The SECURITY DEFINER function is the only path, and it posts the ledger in the same transaction. A trigger still checks the edge for every role, including the owner. |

Limitations of this design:

- The rules exist in two places: `deal_transitions` (seeded by migration 0002)
  and `app/domain/deal_states.py`. An integration test fails if they differ;
  changing the rules needs a new migration.
- The database trusts the `actor` and `actor_user_id` the API passes in. It checks
  participation, but **authentication** (proving who the caller is) arrives in
  Phase 1B.
- There is no admin registry yet: any ACTIVE user id is accepted as ADMIN. The API
  must not expose ADMIN actions before authorization exists.
- A `SECURITY DEFINER` function is powerful. It is owned by a non-superuser,
  pins `search_path`, and is the only function `safepay_app` may execute. Review
  every change to it as security-critical.
- The migrator owns the tables and could disable triggers. It is a deployment
  credential, never used at runtime, and should be stored and rotated separately.

## Transaction pattern

```python
with atomic(session):            # exactly one DB transaction; refuses nesting
    result = transition_deal(    # idempotency claim + SECURITY DEFINER call
        session, deal_id=..., action=DealAction.FUND, actor=Actor.BUYER,
        actor_user_id=..., idempotency_key=request_key, expected_version=...)
# committed here; any exception before this point rolls back everything
```

`lock_for_update(session, Model, id)` is available for future row-locked operations.

## Trust boundary: who is the acting user?

```
 client ──(no route exists in Phase 1A)──▶ API process ──safepay_app──▶ safepay_transition_deal
                                            │ supplies actor + actor_user_id   │ verifies: participant,
                                            │ (must come from an authenticated │ legal transition, ADMIN
                                            │  session in Phase 1B)            │ is an ACTIVE user
```

* The database verifies **participation and state**, not **identity**. Whoever holds
  the `safepay_app` credential can act as any buyer or seller of any deal, as
  SYSTEM (for example `AUTO_RELEASE`, which pays the seller), or as ADMIN with any
  active user id. The API process and its credential are therefore inside the
  trust boundary.
* **Phase 1A exposes no such route.** The only HTTP routes are `GET /health`,
  `GET /ready` and the docs. `tests/unit/test_exposed_surface.py` fails if any other
  route is added, or if the HTTP layer imports `app.services`.
* **Before any money-moving endpoint is exposed (Phase 1B), all of these are required:**
  1. Authentication. `actor_user_id` must come from the server-side session, never
     from the request body.
  2. The API derives `actor` (BUYER/SELLER) from the deal participants. It never
     accepts it from the client.
  3. SYSTEM transitions only from a scheduler. Ideally that runs as a separate
     database role allowed to call a SYSTEM-only function, so the web-facing API
     cannot `AUTO_RELEASE`.
  4. ADMIN transitions only for users in an admin registry, behind separate
     authorization, ideally also via a separate role or function.
  5. An `Idempotency-Key` header (scoped per user, see below), and rate limiting.

## Idempotency

`app/services/idempotency.run_idempotent(session, scope, key, request, operation)`:

1. **Claims** `(scope, key)` with `INSERT … ON CONFLICT DO NOTHING`. If a
   concurrent transaction holds an uncommitted claim, PostgreSQL makes the second
   insert **wait** for it.
2. **Runs** the operation and stores the JSON result in the same transaction.
3. **Repeats with the same request** → returns the stored result without running
   the operation again (`replayed=True`).
4. **Same key, different request** (SHA-256 of canonical JSON) →
   `IdempotencyKeyReusedError`, to be mapped to HTTP 409 later.
5. **Failed attempts are not stored**: the rollback removes the claim, so the
   client can retry with the same key.

6. **Claims must be completed.** A deferred constraint trigger rejects any
   transaction that commits a claim without a response, so a key can never be left
   permanently blocked.

**Scope.** Deal transitions use the scope `deal.transition:<acting user id>`, or
`deal.transition:SYSTEM`. One principal's key can never collide with, block, or
reveal the existence of another principal's key. The request fingerprint covers
the deal, action, actor, user and expected version.

Keys are 1–128 characters from `[A-Za-z0-9._:-]`. Records never expire yet; a
cleanup job must run as the migrator (the app cannot delete records).

## Migrating a Phase 0 database

Phase 0 databases have every object owned by the old `POSTGRES_USER`
superuser, so migration 0002 refuses to run on them. Phase 0 was never
deployed, so the supported path is to **recreate the database**:

```bash
docker compose down -v      # deletes the local volume
cp .env.example .env        # now also needs SAFEPAY_MIGRATOR_PASSWORD / SAFEPAY_APP_PASSWORD
docker compose up --build   # initdb creates the roles; migrate runs 0001 + 0002 as safepay_migrator
```

To keep data instead, run the bootstrap script as a superuser, then
`REASSIGN OWNED BY <old_owner> TO safepay_migrator;`, and then `alembic upgrade head`
as `safepay_migrator`.

## Migration safety

* Migrations run only as `safepay_migrator`, never as a superuser; `migrations/env.py`
  refuses any other role before the first revision. No migration needs superuser
  privileges. Only the one-time role bootstrap does, and the API never does.
* Each revision runs in its own transaction (PostgreSQL DDL is transactional). A
  revision that fails part-way leaves **nothing** behind: no tables, functions,
  grants or `alembic_version` change. A test proves this by sabotaging 0002.
* **Downgrades never silently destroy data.** `DROP TABLE` bypasses the append-only
  triggers, so every destructive downgrade refuses to run while the affected tables
  hold rows. To override, take a backup and pass `-x allow_data_loss=true` explicitly.

## Other controls implemented

* Secrets come only from the environment. `.env` is git-ignored and
  `.env.example` holds placeholders only. Compose fails fast if any of the three
  database passwords is unset.
* `/ready` never echoes connection strings or driver errors.
* **API:**
  - `X-Content-Type-Options: nosniff` and `Cache-Control: no-store`;
  - an explicit CORS allow-list and a validated `X-Request-ID`;
  - OpenAPI docs disabled in production.
* **Web:**
  - `X-Frame-Options: DENY`, `nosniff` and a strict referrer policy;
  - a restrictive `Permissions-Policy` (including `payment=()`);
  - no `X-Powered-By`, and `noindex`.
* **Containers and network:**
  - Containers run as non-root.
  - The database is not published in the base Compose file.
  - Web and API bind to `127.0.0.1` by default.
* **CI:**
  - Fails on high-severity advisories in production npm dependencies.
  - Proves the migration refuses a superuser.
  - Proves the live Compose stack refuses tampering by the app role.

## Remaining risks and required work

* **Authentication and authorization** (Phase 1B): phone OTP, sessions
  (`HttpOnly; Secure; SameSite=Lax`), CSRF protection, rate limiting, an admin
  registry and per-endpoint authorization.
* **Participant and draft writes are not authorized per user yet.** The app role can
  add participants to any DRAFT or PENDING_ACCEPTANCE deal and edit DRAFT terms; the
  database limits *what* can change, but *who* may do it needs Phase 1B auth.
* **Holder of the `safepay_app` credential** can impersonate any participant,
  SYSTEM or ADMIN through `safepay_transition_deal` (see "Trust boundary"). Protect the
  credential like a payment key. Splitting SYSTEM and ADMIN into separate roles is
  recommended for Phase 1B.
* **Availability:** the app role can hold row locks on deals and claims, and can
  raise its own timeouts. A leaked credential could therefore cause lock contention,
  but not financial changes.
* **Lock waits:** `lock_timeout=5s` for the app role means a request that waits
  behind a long-running transition on the same deal or idempotency key fails
  instead of hanging; clients should retry with the same key.
* **App-written audit events** (non-financial) still carry an actor chosen by the app.
  Financial transitions are audited by the database function.
* **Tamper evidence:** a hash chain over audit rows and a periodic reconciliation
  job (total debits = total credits; escrow = amount for FUNDED, DELIVERED and
  DISPUTED deals).
* **Operations:**
  - TLS termination at a reverse proxy, HSTS and a Content-Security-Policy;
  - backups with tested restores;
  - log shipping without PII;
  - credential rotation for all three database roles.
* **Privacy:** minimal personal data, a retention policy, and compliance with
  Mongolia's Law on Personal Data Protection (2021).
* **Dependencies:** the dev-only `braces` advisory in the ESLint toolchain has no
  upstream fix yet; re-check periodically.
