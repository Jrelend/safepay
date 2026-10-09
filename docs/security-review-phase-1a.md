# Phase 1A security review

Scope: PR #2 (database security), reviewed at commit `f454d5c`. Method: code review
plus live attacks against PostgreSQL 17 using the real `safepay_app`,
`safepay_migrator` and superuser roles. Every finding marked fixed has a regression
test that **fails on `f454d5c` against a fresh database** and passes after the fix
(`apps/api/tests/integration/test_security_review.py`).

## Findings (most severe first)

| # | Severity | Finding | Status |
|---|---|---|---|
| 1 | **Medium** (latent) | **Trigger functions did not pin `search_path`.** Deferred constraint triggers, including the ledger-balance check, fire at `COMMIT` with the session's `search_path`, where `pg_temp` is searched first. A role able to create temp tables could shadow `ledger_entries` or `deal_transitions` and bypass the balance check or the transition-legality check. Demonstrated as the schema owner. The app role was protected only because it lacks `TEMPORARY`. | Fixed: all 13 SafePay functions get `search_path = pg_catalog, public, pg_temp`. |
| 2 | **Medium** | **New functions were executable by the app role.** The bootstrap's `ALTER DEFAULT PRIVILEGES … IN SCHEMA public REVOKE EXECUTE … FROM PUBLIC` is a no-op, because PostgreSQL ignores a per-schema revoke of a globally granted default. Any future migration adding a privileged function would have exposed it to `safepay_app` unless its author remembered to `REVOKE`. | Fixed: the global form is used in both the bootstrap and migration 0002. |
| 3 | **Medium** | **Race when creating a wallet account.** Two deals paying the same user concurrently collided on the one-wallet-per-owner index, which `ON CONFLICT (code)` does not cover. The losing release failed with `UniqueViolation` in about 1 of 60 races. No money was lost (atomic rollback), but legitimate releases could fail. | Fixed: untargeted `ON CONFLICT DO NOTHING` and a lookup by natural key. 0 failures in 600 races. |
| 4 | **Medium** | **Downgrades silently destroyed data.** `DROP TABLE` bypasses the append-only triggers, so `alembic downgrade base` would erase ledger and audit history without warning. | Fixed: destructive downgrades refuse while rows exist, unless `-x allow_data_loss=true` is passed. |
| 5 | **Low–Medium** | **Idempotency keys were global across users.** Any principal could block another's key, or learn that it existed (409 vs. success). | Fixed: scope is `deal.transition:<acting user>`. |
| 6 | **Low** | **An uncompleted idempotency claim could be committed** with raw SQL as the app role, blocking that key forever. | Fixed: a deferred constraint trigger requires completion before `COMMIT`. |
| 7 | **Low** | **A deal could leave DRAFT without both parties.** For example, a seller could SUBMIT with no buyer, and a buyer could then be added in PENDING_ACCEPTANCE. | Fixed: transitions out of DRAFT (except CANCEL) require a buyer and a seller. |
| 8 | **Low** | **The app role could create large objects** (`lo_create`), a disk-exhaustion lever for a leaked credential. | Fixed: `EXECUTE` revoked from `PUBLIC` in the bootstrap. |
| 9 | **Info** | The app role can change its own `statement_timeout` / `lock_timeout` (`SET`, `ALTER ROLE … SET`). The docs wrongly called these guard rails. | Docs corrected: they are defaults, not controls. |
| 10 | **High for Phase 1B; not exploitable now** | `safepay_transition_deal` trusts `actor` and `actor_user_id`. The holder of the app credential can act as any participant, as SYSTEM (`AUTO_RELEASE`) or as ADMIN (any active user). | **No route exposes it.** A test now fails if any route other than health/ready/docs is added, or if the HTTP layer imports `app.services`. The Phase 1B prerequisites are documented in `SECURITY.md` ("Trust boundary"). |

## Verified as not vulnerable

All attempted as `safepay_app`:
- **Role change:** `SET ROLE` / `SET SESSION AUTHORIZATION safepay_migrator`, `GRANT safepay_migrator`, `ALTER ROLE … SUPERUSER / BYPASSRLS / CONNECTION LIMIT / RENAME`, changing the migrator's password, `CREATE ROLE`.
- **Ownership and permissions:** `ALTER DATABASE … OWNER`, `ALTER SCHEMA … OWNER`, `REASSIGN OWNED`, self-`GRANT` (it only warns, and the test verifies nothing is gained).
- **Disabling or replacing safety:** `DISABLE TRIGGER`, `DROP TRIGGER`, `session_replication_role` (via `SET` and via `set_config`), `CREATE OR REPLACE` of any SafePay function, `ALTER FUNCTION … SECURITY INVOKER`.
- **Creating objects:** CREATE TABLE / FUNCTION / SCHEMA / TEMP / `pg_temp` function / EXTENSION.
- **Privileged built-ins:** `COPY … TO PROGRAM`, `pg_read_file`, `pg_ls_dir`, `lo_import`, `pg_reload_conf`, calling trigger functions directly.
- **Ledger and audit tampering:** INSERT, UPDATE, DELETE or TRUNCATE on any ledger or audit table, `LOCK` or `SELECT … FOR UPDATE` on ledger tables, `UPDATE deals.status`, editing `deal_transitions`.

**SECURITY DEFINER function** (`safepay_transition_deal`):
- owned by the non-superuser migrator, with a pinned `search_path`;
- no dynamic SQL; all inputs are typed parameters compared in SQL;
- `p_actor` is validated against an allow-list, `p_request_id` is truncated, and unknown deals or actions raise SafePay errors;
- `EXECUTE` is granted to `safepay_app` only, and not to PUBLIC.

**Financial integrity:**
- atomic rollback (exception and DB error);
- concurrent double funding;
- release vs. refund race: exactly one wins in 5 of 5 runs;
- same-key concurrency, and conflicting payloads (sequential and concurrent);
- ledger balanced globally.

**Migrations:**
- a new database initializes with migrator ownership;
- a sabotaged 0002 rolls back completely;
- the superuser and the app role are refused before any revision runs.

## Remaining risks

See `SECURITY.md` → "Remaining risks and required work". The most important: implement
authentication **and** split SYSTEM/ADMIN authority from the web-facing app role
before any money-moving endpoint exists (Phase 1B).
