# SafePay Beta v0.1 — implementation plan and continuation log

> Living document. If work stops mid-way, the **Status** column says exactly
> where to resume. All payments are simulated; no real money, no banks, no QPay.

## Architecture decisions

| Topic | Decision |
|---|---|
| Browser ↔ API | The browser only talks to the **web origin**. A Next.js route handler (`/api/[...path]`) proxies to the API at runtime, forwarding an explicit header allow-list. Cookies are first-party on the web origin. |
| Sessions | Opaque random token in an `HttpOnly; SameSite=Lax` cookie (`Secure` outside local). The DB stores only its SHA-256. Absolute TTL 7 days, idle TTL 24 h. Sessions are revoked on logout, password change/reset and suspension. |
| CSRF | Synchronizer token bound to the session: the `safepay_csrf` cookie (readable by JS) must equal the `X-CSRF-Token` header and the session's stored hash. **Origin** is checked on every unsafe request. |
| Passwords | Argon2id (argon2-cffi). Unknown emails hash a dummy password, so response timing doesn't reveal accounts. |
| Enumeration | Register, login, resend and reset-request return identical responses whether or not the account exists. |
| Email | No real email. Messages go to an `email_outbox` table. In `local`/`test` only, a dev mailbox endpoint (off by default, never in production) lets you complete verification and reset. |
| Rate limiting | DB-backed fixed windows (`rate_limits` table), keyed by IP and by account identifier. |
| Identity | `actor_user_id` always comes from the server-side session. Public endpoints derive BUYER/SELLER from the deal participants; the client never sends an actor. |
| **DB privilege split** | `safepay_app` (public API): only the BUYER/SELLER transition function. `safepay_system` (worker): only the SYSTEM function, which **re-checks eligibility in SQL** (expiry age, inspection window). `safepay_admin` (separate `admin-api` service): only the ADMIN functions, which require the user to be in the `admins` table. Admins are granted only with a CLI that uses the admin DB role. |
| Admin service | Same image, `API_MODE=admin`, its own credentials. The public API container never holds admin or system credentials. |
| Notifications | Written by the transition function itself, so every path (user, system, admin) notifies consistently. |
| Evidence | `dispute_evidence` is append-only (trigger). Files are stored in the DB (≤ 2 MB; png, jpeg or pdf), served only to participants and admins with `Content-Disposition: attachment` and `nosniff`. |
| Escrow safety | New deferred check: escrow and wallet balances can never go negative. |

## Milestones

| # | Milestone | Status |
|---|---|---|
| M1 | Migration 0003: auth tables, system/admin roles, function split, deal terms, invites, disputes, evidence, notifications, rate limits, negative-balance guard; bootstrap update | ✅ |
| M2 | Auth API: register/verify/login/logout/reset/change, sessions, CSRF, rate limits, profile, suspension; tests | ✅ |
| M3 | Deals API: create/edit/invite/join/accept/reject/cancel/fund/deliver/release/refund, history, timeline, wallet; IDOR tests | ✅ |
| M4 | Disputes + evidence, admin-api (review, decision, suspension), worker (expiry, auto-release); privilege tests | ✅ |
| M5 | Mongolian mobile-first UI: all pages | ✅ |
| M6 | Compose (admin-api, worker), CI roles + E2E job, Playwright E2E, docs, final PR | ✅ |

## Bugs found by the M2–M4 HTTP/role tests (fixed)

- **Worker could not auto-release.** The deferred ledger checks fired at COMMIT with the
  caller's privileges, and `safepay_system` cannot read the ledger, so every AUTO_RELEASE
  failed. The deferred integrity checks are now `SECURITY DEFINER` (migration 0003).
  Regression: `test_role_matrix.py::test_worker_expires_and_auto_releases_only_eligible_deals`.
- **Admin grant CLI crashed** (`IndeterminateDatatype` on the audit note) — never
  exercised before E2E. Fixed with an explicit cast; `tests/integration/test_admin_cli.py`.
- **Admin notes leaked to participants** in the dispute view. Fixed in
  `services/disputes.view`. Regression: `test_admin_decision_refunds_and_is_audited`.

## Staging preparation (round 2)

| # | Milestone | Status |
|---|---|---|
| S1 | Release safety: automatic release off by default (0004), regression tests | ✅ |
| S2 | Final security review: findings fixed (incl. admin auth 0005) | ✅ |
| S3 | Private staging stack: Caddy HTTPS edge, isolation, hardening, backups | ✅ |
| S4 | Scenario tests A–L, UI review 390/768/1440 | ✅ |
| S5 | CI staging job, docs (STAGING, security review), PR update | ✅ |
| — | Deploy to a VPS | ⛔ not approved |

Bugs found while doing this (all fixed): empty `ACME_EMAIL` broke the Caddyfile;
`staging-restore.sh` exited 1 after a successful restore (trap); retiring reset tokens
before flushing hit the append-only token guard; `.env.staging.example` was git-ignored.
