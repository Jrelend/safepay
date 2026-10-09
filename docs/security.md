# Security and financial-safety requirements

## Non-negotiable product rules

1. **Simulation only.** SafePay Beta never accepts, holds or transfers real
   money. It integrates no payment provider, bank, card or wallet API.
   `PAYMENTS_SIMULATION_ONLY` is typed `Literal[True]`, so the API refuses to start
   with any other value. Every response is tagged `X-SafePay-Simulation: true` and the UI
   shows a permanent banner.
2. **Integer MNT only.** Money is whole tögrög in `BIGINT`. There are no floats or
   decimals anywhere (Python `int`, TypeScript `bigint`). Column names end in
   `_mnt` (a test enforces this).
3. **Double-entry ledger, no stored balances.** Balances are derived from
   entries; a test fails if any column name contains `balance`.
4. **Immutable history.** Ledger and audit tables are append-only, enforced by
   DB triggers. Corrections are new reversing transactions.
5. **The backend is authoritative** for deal state. Clients request actions,
   which are checked against the state machine and the caller's role.
6. **Atomic and idempotent** financial operations (design in
   `docs/architecture.md`; the schema already has a unique `idempotency_key`).

## Implemented in Phase 0

* DB-level invariants: balanced journals, sealing, append-only tables, CHECK constraints.
* Secrets come only from the environment. `.env` is git-ignored and `.env.example` holds
  placeholders only. Compose fails fast if `POSTGRES_PASSWORD` is unset.
* `/ready` never echoes connection strings or driver errors.
* API: `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`, an explicit
  CORS allow-list, a validated `X-Request-ID`, and OpenAPI docs disabled in production.
* Web: `X-Frame-Options: DENY`, `nosniff`, a strict referrer policy,
  a restrictive `Permissions-Policy` (including `payment=()`), no `X-Powered-By`,
  and `noindex`.
* Containers run as non-root. The base Compose file does not publish the DB, and web
  and API bind to `127.0.0.1` by default.

## Required before any public beta (Phase 1 and later)

* Authentication (phone OTP or similar) with rate limiting and lockout;
  session cookies `HttpOnly; Secure; SameSite=Lax`; CSRF protection.
* Authorization on every deal endpoint: only participants can access a deal, an admin role
  resolves disputes, and every admin action is audited.
* Separate DB roles: the app role gets only `INSERT`/`SELECT` on ledger and
  audit tables, and migrations run as a different owner role.
* TLS termination at a reverse proxy, HSTS and a Content-Security-Policy.
* Structured logging without PII; log and metric shipping; backups with tested
  restores; dependency and container scanning in CI. Resolve the `npm audit`
  findings in dev-only ESLint dependencies.
* Tamper evidence for audit rows (a hash chain) and a periodic ledger
  reconciliation job (total debits = total credits; the escrow invariant holds).
* Privacy: minimal personal data, a retention policy, and compliance with
  Mongolia's Law on Personal Data Protection (2021).
