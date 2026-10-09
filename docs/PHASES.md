# Development phases

## Phase 0: Foundation ✅

Monorepo, FastAPI and Next.js apps, PostgreSQL 17 with Alembic, an initial schema with
DB-enforced ledger and audit invariants, a pure deal state machine, a Mongolian
mobile-first UI shell, health and readiness endpoints, Docker Compose, CI and docs.

## Phase 1A: Database security ✅ (merged)

* Separate `safepay_migrator` / `safepay_app` roles, least-privilege grants, and role
  checks in migrations and `/ready`.
* The SECURITY DEFINER transition function: row lock, DB-enforced transitions and
  actor checks, atomic escrow posting, version bump, audit event.
* No double funding, release or refund; idempotency service; guard triggers.

## Beta v0.1 (this PR) — see `BETA_PLAN.md`

Phases 1B–5 of the beta brief, all with **simulated** payments only.

| Area | Status | Notes |
|---|---|---|
| Auth & security (1B) | ✅ | Email + password (Argon2id), email verification, password reset/change, sessions with expiry and revocation, CSRF + Origin, rate limits, no enumeration, profile, suspension. Phone OTP replaced by email (no SMS provider in a simulation). |
| DB privilege split (1B) | ✅ | `safepay_app` / `safepay_system` / `safepay_admin`, each with only its own function; separate `admin-api` and `worker` services. |
| Deals (2) | ✅ | Create, invite (link, optional email restriction), join, edit/cancel draft, submit/accept/decline, history, details, physical/digital/service, face-to-face/courier/digital, no self-deals, terms frozen once both accept. |
| Simulated escrow (3) | ✅ | Fund, deliver, confirm/release, seller refund, worker auto-release and expiry; double-entry, atomic, row locks, idempotency, no negative balances. |
| Disputes (4) | ✅ | Open with reason, statements, PNG/JPEG/PDF evidence (private, append-only), admin notes, admin decision (release/refund), timeline, audit. |
| Mongolian mobile UI (5) | ✅ | Landing, register, login, verify, reset, dashboard, create/edit deal, deal details, history, invite, notifications, profile, security, dispute, admin (disputes, users, audit), dev mailbox. |
| Tests | ✅ | pytest (unit + PostgreSQL integration incl. HTTP), Vitest, Playwright E2E. |

## Before a private beta (not started)

* Real transactional email; admin MFA; reverse proxy that sets `X-Forwarded-For`;
  CSP + HSTS; backups; monitoring of the worker; audit hash chain + reconciliation job;
  privacy policy and terms in Mongolian; retention policy; load testing; external
  security review.

Real payment integration is **out of scope** for the entire beta.
