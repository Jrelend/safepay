# Development phases

## Phase 0: Foundation ✅

Monorepo, FastAPI and Next.js apps, PostgreSQL 17 with Alembic, an initial schema with
DB-enforced ledger and audit invariants, a pure deal state machine, a Mongolian
mobile-first UI shell, health and readiness endpoints, Docker Compose, CI and docs.

## Phase 1: Core simulated escrow (needs approval)

* Phone-based sign-up and login (OTP simulated in dev), sessions, rate limits.
* Create a deal → invite the counterparty → accept; deal detail and list pages.
* Ledger service: `post_transaction()` with idempotency keys; fund (simulated),
  mark delivered, confirm receipt → release; seller-initiated refund.
* An atomic action-endpoint pattern (`SELECT … FOR UPDATE`, version check,
  ledger + status + audit in one transaction) and an `Idempotency-Key` header.
* API amounts serialized as strings to avoid JavaScript precision loss.
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
