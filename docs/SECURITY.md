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

## Database security model

### Roles

| Role | Used by | Attributes |
|---|---|---|
| `POSTGRES_USER` (superuser) | Initialising a fresh volume only. Nothing at runtime uses it. | superuser |
| `safepay_migrator` | `alembic upgrade` and the `app.cli` admin grant tool. Owns the `public` schema and **every** table, trigger and function. | `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS` |
| `safepay_app` | The public API (`api` service). | `NOSUPERUSER … NOINHERIT`, `CONNECTION LIMIT 50`; default `statement_timeout=15s`, `lock_timeout=5s`, `idle_in_transaction_session_timeout=30s` |
| `safepay_system` | The background `worker` only (expiry, auto-release). | `NOSUPERUSER … NOINHERIT`, `CONNECTION LIMIT 5` |
| `safepay_admin` | The separate `admin-api` service only. | `NOSUPERUSER … NOINHERIT`, `CONNECTION LIMIT 10` |

Each service receives **only its own** credential; the public API container holds no
system or admin credential (CI checks this on the live Compose stack).

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

### What each runtime role can do (migration 0003)

Generated from `information_schema` on a database at head `0003`.

| Table | `safepay_app` (public API) | `safepay_system` (worker) | `safepay_admin` (admin API) |
|---|---|---|---|
| `ledger_accounts`, `ledger_transactions`, `ledger_entries` | SELECT | – | SELECT |
| `audit_events` | SELECT, INSERT (timestamp forced by DB) | – | SELECT |
| `deals` | SELECT, INSERT (DRAFT, v1 only); UPDATE of draft terms + invite columns only — **never `status`** | SELECT | SELECT |
| `deal_participants` | SELECT, INSERT (before acceptance) — **no UPDATE** (acceptance only via the transition function) | – | SELECT |
| `users` | SELECT, INSERT; UPDATE `display_name, phone_e164, password_hash, email_verified_at, updated_at` — **not `status`** | – | SELECT |
| `admins` | SELECT | – | SELECT |
| `sessions` | SELECT, INSERT; UPDATE `last_seen_at, revoked_at` | – | SELECT |
| `auth_tokens` | SELECT, INSERT; UPDATE `used_at` | – | – |
| `disputes` | SELECT | – | SELECT |
| `dispute_evidence` | SELECT, INSERT (participants, open dispute; append-only) | – | SELECT, INSERT (admin notes) |
| `notifications` | SELECT, INSERT; UPDATE `read_at` | – | – |
| `email_outbox`, `rate_limits` | SELECT, INSERT (`rate_limits.count` UPDATE) | SELECT, DELETE (cleanup) | – |
| `idempotency_records` | SELECT, INSERT (claim); UPDATE `response, completed_at` once | – | – |
| `deal_transitions`, `alembic_version` | SELECT | `alembic_version` | SELECT |

Function `EXECUTE` (verified by `tests/integration/test_role_matrix.py`):

| Function | app | system | admin |
|---|---|---|---|
| `safepay_transition_deal(deal, action, user, version, note, request_id)` — actor **derived** from `deal_participants` | ✅ | ❌ | ❌ |
| `safepay_system_transition_deal(deal, action, request_id)` — EXPIRE / AUTO_RELEASE, **re-checks** the 7-day expiry and inspection window in SQL | ❌ | ✅ | ❌ |
| `safepay_admin_transition_deal`, `safepay_admin_resolve_dispute`, `safepay_admin_set_user_status` — require an ACTIVE row in `admins`; an admin can never act on a deal they participate in, nor change their own status | ❌ | ❌ | ✅ |
| `safepay__apply_transition` (internal), all trigger functions | ❌ | ❌ | ❌ |

No runtime role can write to `admins`; admins are granted only with
`python -m app.cli grant-admin <email>` using the owner (migrator) credential, which is audited.

The deferred integrity checks (ledger balanced, no negative escrow/wallet, idempotency
completion) are `SECURITY DEFINER`: they fire at `COMMIT`, outside the transition
function, so they must not depend on what the calling role may read. (Before this,
the worker's AUTO_RELEASE failed because `safepay_system` cannot read the ledger —
found by the role-matrix tests.)

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
- Since migration 0003 the public function no longer accepts an `actor`: it derives
  BUYER/SELLER from `deal_participants` for the session's user. SYSTEM and ADMIN go
  through separate functions granted to separate roles (see the tables above).
- `SECURITY DEFINER` functions are powerful. They are owned by a non-superuser,
  pin `search_path`, and each runtime role may execute exactly its own entry point.
  Review every change to them as security-critical.
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
 browser ──HTTPS──▶ web (Next.js) ──/api/* proxy──▶ api (safepay_app) ──▶ safepay_transition_deal(user from session)
                         │  allow-listed headers         └ identity = server-side session; actor derived in SQL
                         └──/api/admin/*──────────▶ admin-api (safepay_admin) ──▶ safepay_admin_* (user must be in admins)
                                                   worker (safepay_system) ──▶ safepay_system_transition_deal (eligibility re-checked)
```

* **Identity always comes from the session cookie**, looked up server-side. No route
  accepts `actor`, `actor_user_id` or `acting_user_id`; unknown JSON fields are ignored
  and `tests/unit/test_exposed_surface.py` fails if any request model declares one.
* **BUYER/SELLER is derived by the database** from `deal_participants`. A non-participant
  gets `404` (no existence oracle) from every deal, dispute and evidence route.
* **SYSTEM authority lives only in the worker's role**, and the SQL function re-checks
  that the deal is actually eligible, so even a stolen worker credential cannot release
  money early.
* **ADMIN authority lives only in the admin API's role**, and each admin function
  re-checks the `admins` registry. The public API does not mount `/admin` at all.
* The holder of a role credential is still trusted for that role's scope. Protect each
  like a payment key; they are separate so a public-API compromise cannot pay out.

## Application security (Beta v0.1)

| Control | Implementation |
|---|---|
| Passwords | Argon2id (argon2-cffi defaults), 10–128 chars, common-password and email-equal checks, transparent rehash. Unknown emails verify against a dummy hash (timing). |
| Account enumeration | Register, resend, reset-request return the same response for known and unknown emails; login failures are identical. Tested. |
| Sessions | 256-bit random token in an `HttpOnly; SameSite=Lax; Path=/` cookie (`__Host-` + `Secure` when `COOKIE_SECURE`/non-local). DB stores SHA-256 only. Absolute 7-day and idle 24-hour expiry. Revoked on logout, password change (other sessions), password reset (all) and suspension (all). |
| CSRF | Synchronizer token: `safepay_csrf` cookie must equal `X-CSRF-Token` and match the session's stored hash, on every authenticated unsafe request. Plus an **Origin allow-list** check on all unsafe requests (also blocks login CSRF). |
| Rate limits | DB-backed fixed windows: login per IP and per email, registration per IP, email actions per IP and per address, token attempts per IP, mutations per user, evidence uploads per user. |
| Email tokens | Single-use, hashed, short-lived (verify 24 h, reset 1 h); verification requires a click (link scanners can't consume it). |
| Idempotency | `Idempotency-Key` header required on every deal action, scoped per user; the UI generates one key per confirmation dialog so double clicks and retries execute once (E2E-tested). |
| Evidence files | ≤ 2 MB; type **sniffed** from magic bytes (PNG, JPEG, PDF only; SVG/HTML rejected); file names sanitized; served only to participants/admins as `attachment` with `nosniff`, `CSP: sandbox` and `no-store`. Append-only. |
| Admin notes | Never returned to participants (regression-tested). |
| Web proxy | Only an allow-list of request headers is forwarded (`cookie`, `content-type`, `x-csrf-token`, `idempotency-key`, `origin`, …); `/health`, `/ready`, `/docs` are not exposed through it; path segments are validated (no traversal or encoded slashes); bodies capped at 3 MB. |
| Redirects | Post-login `next` accepts only same-site relative paths (unit + E2E tested). |
| Dev mailbox | `/dev/mailbox` exists only when `APP_ENV` is `local`/`test` **and** `DEV_MAILBOX_ENABLED=true`; never in staging/production (unit-tested). |

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

## Remaining risks and required work (before a private beta)

* **Client IP behind proxies.** The API trusts the first `X-Forwarded-For` hop only when
  `TRUST_PROXY_HEADERS=true`, and the web proxy forwards the right-most hop it received.
  Next.js fills `X-Forwarded-For` from the socket only when the header is absent, so
  **production must run a reverse proxy that overwrites `X-Forwarded-For`** (e.g. nginx
  `proxy_set_header X-Forwarded-For $remote_addr`). Without it, per-IP limits can be
  evaded by spoofing the header (per-account limits still apply). The API port should
  not be published publicly.
* **No real email delivery.** Verification and reset emails go to `email_outbox`; a
  transactional email provider (with SPF/DKIM) is needed before real users.
* **No MFA / step-up auth for admins.** Admin sessions are ordinary sessions on the
  admin API. Add TOTP/WebAuthn and IP allow-listing for `/admin` before a beta.
* **Security headers.** `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`,
  `Permissions-Policy` are set; a strict Content-Security-Policy and HSTS (at the TLS
  proxy) are still to do.
* **Tamper evidence:** a hash chain over audit rows and a periodic reconciliation job
  (total debits = total credits; escrow = amount for FUNDED/DELIVERED/DISPUTED deals).
* **Data protection:** retention policy for sessions, evidence files and the outbox;
  evidence is stored in PostgreSQL (fine at ≤ 2 MB per file for a beta, move to object
  storage with encryption later); compliance with Mongolia's Law on Personal Data
  Protection (2021).
* **Operations:** TLS, backups with tested restores, log shipping without PII,
  credential rotation for all five database roles, monitoring of worker passes.
* **Abuse:** no KYC, fraud scoring or deal-amount limits per user beyond the global
  100 ₮ – 100 bn ₮ range. All money is simulated, so this is acceptable only while the
  product stays a simulation.
* **Dependencies:** `npm audit --omit=dev` is clean; dev-only advisories in the lint
  toolchain are tracked in CI.
