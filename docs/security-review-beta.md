# Beta v0.1 final security review (staging preparation)

Scope: PR #3 at `4fad76d` plus the fixes in this round. Method: an independent
read-only review (code + DB grants), every candidate finding re-traced and
reproduced before fixing, and a regression test per fix (real PostgreSQL roles).

## Findings and fixes

| # | Severity | Finding | Fix | Regression test |
|---|---|---|---|---|
| 1 | **High (financial policy)** | An expired inspection window released escrow automatically (worker → `AUTO_RELEASE`). Beta policy requires buyer confirmation or an admin decision. | Migration 0004: `platform_policy.auto_release_enabled = false` (owner-only), checked first in the SYSTEM function (SPD10); worker skips release unless configured; UI no longer promises it. Downgrade below 0004 refuses while deals are DELIVERED. | `test_release_safety.py` (20), `test_beta_scenarios.py::test_i_*`, migration test |
| 2 | **Medium** | A leaked `safepay_app` credential could become admin: the admin API trusted public `sessions` and `users.password_hash`, both writable by the app role. | Migration 0005: admin-only password (Argon2id) + TOTP (RFC 6238, single-use steps) stored on `admins` and readable only by `safepay_admin`; `admin_sessions` writable only by `safepay_admin` (8 h / 30 min idle, `SameSite=Strict`, own CSRF); app role sees only `admins.user_id`; admin role cannot read public sessions. | `test_admin_auth.py` (10), incl. the exact escalation attempt |
| 3 | Medium | Per-email rate limits keyed on the raw string: Unicode look-alike domains (fullwidth letters/dots) normalize to the same account but got separate budgets. | Key on `normalize_email()` (same as the account lookup). | `routes_auth.email_key` + auth suite |
| 4 | Medium (deployment) | Client IP for rate limits spoofable via `X-Forwarded-For` when the web proxy is reachable directly. | Staging puts Caddy in front, which replaces client-supplied XFF with the real address (verified); API/web never published. Documented requirement for any deployment. | Local Caddy test; CI `staging` job |
| 5 | Low/Med | Admins could view/annotate disputes on their own deals, read evidence, or change the status of a counterparty. | `403 conflict_of_interest` for dispute detail, notes, evidence, decision (also in SQL) and user status when the admin shares a deal. | `test_api_disputes_admin.py::test_admin_cannot_decide_own_deal` |
| 6 | Low/Med | Phone numbers: enumeration via `409 phone_taken` with no rate limit; unverified numbers shown to counterparties. | `PROFILE_PER_USER` limit (10/h); UI labels the phone "баталгаажаагүй" (unverified). Phone OTP remains future work. | auth suite |
| 7 | Low | Web proxy read chunked bodies (no `Content-Length`) fully before the 3 MB check. | Streamed read that aborts past the cap. | `proxy.test.ts` |
| 8 | Low | Append-only evidence had no per-dispute cap (disk filling). | ≤ 10 files and ≤ 50 statements per party per dispute (advisory-locked count). | dispute suite |
| 9 | Low | Invite tokens (bearer secrets in URL paths) written to uvicorn access logs. | App access log with redaction; uvicorn access log off; Caddy access log off. | `test_runtime_safety.py` |
| 10 | Config | Dev mailbox / insecure cookies could be enabled on a server by copying `.env.example`. | `staging`/`production` refuse to start with the mailbox, `COOKIE_SECURE=false` or non-https origins; web proxy forwards `/api/dev` only with `ENABLE_DEV_ROUTES=true`. | `test_runtime_safety.py`, `test_exposed_surface.py` |
| 11 | Low | Old reset links stayed valid after a reset/change; sessions opened on a pre-registered (attacker-created) account survived verification. | Reset/change retire outstanding reset tokens; first verification revokes existing sessions. | auth suite |
| 12 | Info | DB outage produced a generic 500. | Clean `503 service_unavailable` JSON with `Retry-After`, no internals; liveness unaffected. | `test_runtime_safety.py` |

## Verified as not vulnerable (this round)

* **Sessions:** hashed tokens; expiry, idle timeout and revocation on every request; suspension
  re-checked; `__Host-` cookies.
* **CSRF:** Origin required on every unsafe request (`null`/missing rejected), plus a
  synchronizer token compared in constant time. No GET has side effects.
* **IDOR:** every deal, timeline, escrow, wallet, dispute and evidence route returns 404 to
  non-participants. Draft edits and invites are creator-only and DRAFT-only (also
  enforced by triggers).
* **SECURITY DEFINER functions:** `search_path` pinned, no dynamic SQL, actor derived in SQL,
  SYSTEM/ADMIN entry points separated per role, PUBLIC EXECUTE revoked.
* **Ledger:** append-only; balanced and non-negative deferred checks (SECURITY DEFINER);
  deterministic escrow keys; one settlement per deal; row locks; per-user idempotency.
* **Evidence:** type sniffed from content (PNG/JPEG/PDF), names sanitized, downloads served
  as attachments with `sandbox` CSP and `nosniff`; admin notes hidden from participants.

## Residual risks

See `SECURITY.md` → "Remaining risks". The main ones:
* no real email delivery;
* no phone verification;
* pre-registration of someone else's email is still possible (their verification
  kills the squatter's sessions, but not the squatter's password — the owner should reset);
* `'unsafe-inline'` in the CSP (needed by Next.js without nonces);
* a compromised `safepay_admin` credential is still an admin.
