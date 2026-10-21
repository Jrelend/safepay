# Public beta demo mode (`BETA_DEMO_MODE`)

SafePay Beta is a **demo**. No real money exists anywhere in it: payments are
hard-locked to simulation (`PAYMENTS_SIMULATION_ONLY`, `PAYMENT_MODE=simulation`),
and there is no bank or payment-processor integration.

`BETA_DEMO_MODE` lets external testers try the complete escrow workflow without
email verification:
1. register with an email address and password;
2. sign in immediately;
3. create or join deals and run them to the end.

**It is off by default.** Production refuses to start with it.

## What changes when it is on

| | Demo mode off (default) | Demo mode on |
|---|---|---|
| New accounts | normal (`users.is_demo = false`) | **demo** (`users.is_demo = true`), set once at registration |
| Deal workflows for unverified accounts | refused (`email_not_verified`) | **allowed for demo accounts** |
| Accounts registered while the mode was off | need verification | **still need verification** (never exempted) |
| Sign-in, sessions, `__Host-` cookies, CSRF + Origin checks, rate limits | unchanged | unchanged |
| Authorization (participants only, role per action, IDOR → 404) | unchanged | unchanged |
| Admin: separate admin password + TOTP, admin IP allow-list | unchanged | unchanged |
| Simulated ledger, idempotency, escrow invariants | unchanged | unchanged |

**Available workflow** (the existing state machine; nothing was added or relaxed):
- **Normal path:** create, invite/join, submit terms, accept, fund (simulated), mark
  delivered, confirm receipt (release to the seller).
- **Exits:**
  - decline or cancel before payment;
  - seller refund after funding or delivery;
  - dispute, decided by an admin (refund to the buyer, or release to the seller).

**Not available:** automatic release. It stays disabled by platform policy.

**On screen:**
- Every page shows **"DEMO — SIMULATED MONEY — NO REAL PAYMENTS"** in the top
  banner, next to the Mongolian "Туршилтын орчин" notice.
- Every screen and confirmation dialog that shows or moves money repeats it next to
  «ТУРШИЛТЫН ТӨЛБӨР — БОДИТ МӨНГӨ БИШ».
- Demo deals are labelled `DEMO` beside their reference.
- Demo accounts see a "Демо бүртгэл" note on their profile.
- Admins see a `демо` tag in the user list.

## Two keys: API setting and database policy

Demo access needs **both** of these:

1. **`BETA_DEMO_MODE=true`** for the public API. The API checks it in
   `require_verified_user` (`may_transact` in `app/api/auth_context.py`).
2. **`platform_policy.beta_demo_enabled = true`** in the database.
   - Only the schema owner can change it, with
     `python -m app.cli set-beta-demo on|off`. Each change is written to
     `audit_events`.
   - The transition core (`safepay__apply_transition`, `SECURITY DEFINER`) is the
     only way a buyer or seller moves a deal or simulated money. It accepts an
     unverified actor only when that actor is a demo account **and** this policy
     is on.
   - So a stolen runtime credential (`safepay_app`) can neither enable demo access
     nor exempt a real account.

The API's `/ready` fails (`checks.beta_demo`) whenever the two keys disagree, so the
deploy smoke test catches a half-configured state.

**On staging** the `migrate` step syncs the database policy to `BETA_DEMO_MODE`
from `.env.staging` on every deploy. This is a no-op when they already match.

## Demo data is kept apart

- **Flags:**
  - `users.is_demo` and `deals.is_demo` are `NOT NULL`, default false, and set at
    insert.
  - The runtime role has **no UPDATE privilege** on either column, so they cannot be
    flipped later.
- **No mixing:** demo and non-demo accounts never share a deal.
  - The API refuses with `demo_mismatch`.
  - Two triggers refuse it again in the database: a deal's flag must equal its
    creator's, and every participant's flag must equal the deal's.
- **Admins:** admins are staff with a **verified, non-demo** account.
  `app.cli grant-admin` refuses unverified addresses. Admins decide demo disputes
  through the admin API as `ADMIN`, never as a deal party.
- **Finding demo data later**, e.g. before any future real-money release:

  ```sql
  SELECT count(*) FROM users WHERE is_demo;   -- demo accounts
  SELECT count(*) FROM deals WHERE is_demo;   -- demo deals (and, via deal_id, their
                                              -- escrow accounts, disputes, audit events)
  ```

  Ledger and audit tables are append-only by design. Deleting demo data is a separate,
  reviewed operation, and **not part of this change**.

## Turning it on and off (staging) — 🔒 needs approval

```bash
# .env.staging
BETA_DEMO_MODE=true
# plus, for testers without the shared basic-auth login, SITE_ACCESS=public (PR #6)

docker compose -f compose.staging.yaml --env-file .env.staging up -d migrate api
scripts/staging-wait.sh && scripts/staging-smoke.sh   # /ready must agree on both keys
```

**Turning it off:** set `BETA_DEMO_MODE=false` and run the same commands.
- Unverified demo accounts can still sign in and read their deals, but cannot act on
  them.
- Nothing is deleted.
- Accounts stay demo accounts if it is turned on again later.

## Security audit (this change)

Every item below is covered by `apps/api/tests/integration/test_beta_demo_mode.py`
(HTTP + real PostgreSQL roles) and/or `apps/web/e2e/demo-escrow.spec.ts` (browser,
two independent users).

| Area | Check | Result |
|---|---|---|
| **Verification bypass scope** | Only demo accounts skip verification, and only while both keys are on. Non-demo accounts are refused even when the mode and policy are on, by the API and by the DB function called directly. A client cannot request a demo account (an extra `is_demo` in the registration body is ignored). | ✅ |
| **Authorization** | Strangers get 404 for deals, timelines and escrow, and every action is refused. Each party can take only their own role's actions: the seller cannot fund or confirm, the buyer cannot deliver or refund, and neither can perform `AUTO_RELEASE` or `RESOLVE_*`. Parties cannot reach the admin API. | ✅ |
| **Cross-user data** | Deal lists include only the user's own deals. Demo and non-demo accounts cannot join each other's deals (API and DB triggers). | ✅ |
| **Balance manipulation** | There is no endpoint that credits a wallet, and the wallet balance is derived from the immutable double-entry ledger (every transaction is balanced). The amount is frozen after submission. Funding is idempotent, and a second funding or release is refused. Simulated money leaves escrow exactly once. | ✅ |
| **CSRF, Origin, rate limits** | Unchanged in demo mode: requests without a CSRF token or from a foreign Origin are refused (403), and the registration flood limit returns 429. | ✅ |
| **Admin** | Password + TOTP + admin IP allow-list are unchanged. Demo accounts cannot be granted admin. An admin cannot decide a deal they are party to. | ✅ |
| **Flag tampering** | The runtime role cannot UPDATE `is_demo` on users or deals, cannot change `platform_policy`, and cannot insert mixed participants or a deal flagged differently from its creator. | ✅ |
| **Email-restricted invitations** *(found and fixed here)* | Invitations restricted to an email address trusted the joiner's address. In demo mode addresses are unverified, so anyone could register the invited address and take the invitation. **Fix:** a restricted invitation now requires a verified joiner. Unverified (demo) creators cannot set a restriction (`invite_email_unavailable`), and the form hides the field for them. | ✅ fixed |

## Known limitations and risks (accepted for a demo)

- **No proof of email ownership.** A demo account can use any address, including
  someone else's.
  - No email is sent in demo mode, so nobody is contacted.
  - Counterparties see a self-chosen display name. Treat names and addresses as
    unverified.
- **Automated sign-ups.** With no verification and no CAPTCHA, the per-IP limits are
  the only brake:
  - registration: 10 per hour per IP;
  - login: per-IP and per-email limits.
  
  A distributed actor could create many demo accounts. Watch account growth and
  disk use. A CAPTCHA can be added later if abused.
- **Demo data accumulates** in the same database (flagged, never mixed). Before any
  real-money release, plan a reviewed purge or a fresh database.
- **Public access** (no shared basic-auth login) comes from `SITE_ACCESS=public` in
  PR #6. This PR does not change the edge.
