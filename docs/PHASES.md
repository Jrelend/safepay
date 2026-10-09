# Development phases

## Phase 0: Foundation ✅

Monorepo, FastAPI and Next.js apps, PostgreSQL 17 with Alembic, an initial schema with
DB-enforced ledger and audit invariants, a pure deal state machine, a Mongolian
mobile-first UI shell, health and readiness endpoints, Docker Compose, CI and docs.

## Phase 1A: Database security ✅ (in review)

* Separate `safepay_migrator` / `safepay_app` roles, least-privilege grants, and role
  checks in migrations and `/ready`.
* The `safepay_transition_deal` SECURITY DEFINER function: row lock, DB-enforced
  transitions and actor checks, atomic escrow posting, version bump, audit event.
* No double funding, release or refund (deterministic keys plus partial unique
  indexes).
* A reusable idempotency service (replay, 409 on mismatch, concurrency-safe) and an
  `atomic()` transaction pattern.
* Server-generated audit and acceptance timestamps; guard triggers.
* Integration tests for privilege escalation, tampering, races and rollback.

## Phase 1B: Authentication and deal API (needs approval)

* Phone-based sign-up and login (OTP simulated in dev), sessions, rate limits, CSRF.
* An admin registry, so ADMIN transitions require a real admin.
* HTTP endpoints over the Phase 1A services: create deal → invite → accept;
  fund (simulated) → deliver → confirm/release; refund. `Idempotency-Key`
  header → `run_idempotent`; `IdempotencyKeyReusedError` → 409.
* API amounts serialized as strings; deal list and detail pages in Mongolian.
* Playwright end-to-end tests of the happy path.

## Phase 2: Disputes and operations

* Opening a dispute with evidence (text and images), an admin console, release or refund
  resolutions, and a full audit timeline per deal.
* Expiry and auto-release jobs (scheduler) and notifications (SMS and e-mail
  simulated).
* A reconciliation job and admin ledger views.

## Phase 3: Hardening and VPS beta

* Reverse proxy with TLS, separate DB roles, backups, monitoring and alerting,
  CSP, a security review, load testing, and a privacy policy and terms in Mongolian.

Real payment integration is **out of scope** for the entire beta.
