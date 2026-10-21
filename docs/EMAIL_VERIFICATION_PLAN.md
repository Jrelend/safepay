# Real email delivery for SafePay: implementation plan

**Status: plan only.** Nothing is purchased, configured or deployed. Every step marked
🔒 needs explicit approval. Payments stay simulated throughout.

## Why this is needed

Opening the web app with `SITE_ACCESS=public` (see `DEPLOY_DIGITALOCEAN.md` §9a) is only
useful once strangers can complete sign-up. Today they can't:

- **Emails are simulated.** `apps/api/app/services/accounts.py` writes every email to the
  `email_outbox` table, and nothing is ever sent:
  - `verify_email`
  - `account_exists`
  - password reset
  - `password_changed`
- **The worker only purges them.** `apps/api/app/worker.py` deletes outbox rows after 3
  days.
- **Deals require a verified email.** All deal actions use `require_verified_user`
  (`apps/api/app/api/auth_context.py`), so an unverified account is stuck.
- **Testers depend on an operator.** In the closed beta, an operator relays links by hand
  with `python -m app.cli outbox <email>`. That does not scale to the public.

## What emails SafePay sends

These are transactional only: no marketing and no bulk sends.

| Template | Trigger | Contains |
|---|---|---|
| `verify_email` | registration, "resend" | one-time verification link (token, TTL `VERIFY_TTL`) |
| `account_exists` | registration with an existing address | login link (no token) |
| `password_reset` | forgot password | one-time reset link (token) |
| `password_changed` | password change or reset | notice only |

**Expected volume** for the beta: tens to a few hundred emails a month. Any provider's
entry tier is enough.

## Provider comparison

Prices below come from third-party pricing trackers as of October 2026; sources
sometimes disagree. **Check each provider's own pricing page before choosing.**

| | Postmark | Amazon SES | Resend | Mailgun |
|---|---|---|---|---|
| **Free option** | 100 emails/month, no overage (enough to test, not to launch) | 3,000/month for the first 12 months (new AWS accounts) | 3,000/month, capped at 100/day | 100/day |
| **First paid tier** | Basic **$15/mo** for 10,000; then $1.80 per 1,000 | Pay as you go, about **$0.10 per 1,000**; no minimum | Pro about **$20/mo** for 50,000 | Basic **$15/mo** for 10,000 |
| **Likely cost for the beta** | $0 (testing) → $15/mo | ≈ $0–1/mo | $0 (within 100/day) → $20/mo | $0 → $15/mo |
| **Transactional focus** | Yes: transactional-only streams, strong reputation | General purpose | Yes, developer-focused | General purpose |
| **Onboarding** | Account approval review before sending to arbitrary recipients | Starts in a **sandbox** (verified recipients only); production access needs a support request | Domain verification, then send | Domain verification; account review for some regions |
| **Setup effort** | Low (HTTP API, good docs) | Medium-high (IAM user/policy, region, sandbox exit, bounce handling via SNS) | Low (HTTP API) | Low-medium |
| **Data location** | US | Region of your choice (e.g. `ap-southeast-1` Singapore, next to the droplet) | US (EU option) | US or EU |
| **Logs and retention** | 45 days default (configurable) | None by default (CloudWatch/SNS if you set it up) | Short on free | 1–5 days on low tiers |

### Recommendation

**Postmark (Basic, $15/month)** for the public beta:
- **Deliverability:** it has the best reputation for one-time links, which matter most here
  (a verification email in spam blocks sign-up).
- **Integration:** it is the simplest, with a single HTTPS API and per-message status.
- **Content:** it separates transactional streams and refuses marketing content, which
  suits us.

**Amazon SES** is the low-cost alternative (≈ $0–1/month). It's worth it if you already
use AWS or want data in Singapore, but setup and the sandbox approval take longer, and
you must handle bounces and complaints yourself.

**Resend's** free tier (100/day) is fine for a soft launch, but a sign-up spike would hit
the daily cap and lock new users out until the next day.

The code below is provider-neutral: one small adapter per provider, chosen by
configuration. Switching later is a configuration change, not a rewrite.

## DNS records needed on `dhdbot.xyz` 🔒

These go on the **existing** `dhdbot.xyz` zone. They are additive and do not change any
existing record.

**Recommendation:** send from a dedicated subdomain such as **`mail.safepay.dhdbot.xyz`**
(or `safepay.dhdbot.xyz`). That keeps SafePay's sending reputation, and any SPF change,
away from the main `dhdbot.xyz` mail.

| Record | Name (example) | Purpose | Notes |
|---|---|---|---|
| DKIM (TXT or CNAME) | provider-specific selector, e.g. `20261021pm._domainkey.mail.safepay` | Signs mail so receivers can verify it | Postmark: 1 TXT; SES: 3 CNAMEs; Resend/Mailgun: TXT |
| Return-Path / bounce (CNAME or MX + TXT) | e.g. `pm-bounces.mail.safepay` → `pm.mtasv.net` | Custom Return-Path, so SPF aligns for DMARC | SES uses a "MAIL FROM" subdomain with MX + SPF TXT |
| SPF (TXT) | the Return-Path / MAIL FROM subdomain | Authorises the provider's servers | Only on the sending subdomain; **do not edit the apex `dhdbot.xyz` SPF** |
| DMARC (TXT) | `_dmarc.mail.safepay` | Tells receivers what to do with mail that fails | Start `v=DMARC1; p=none; rua=mailto:…`, then move to `quarantine` once reports are clean |

**Before adding these records, check the existing zone** (read-only, as in
`DEPLOY_DIGITALOCEAN.md` §3a.1):
- whether `dhdbot.xyz` already has a DMARC record (a subdomain inherits the parent's
  policy unless it has its own);
- any existing SPF record;
- any MX records.

Record the before/after diff as in §3a. TTL 300 while testing.

**No inbound mail is needed**: replies can go to a monitored address via `Reply-To`.

## Security considerations

- **Credentials.** The provider's API key would live in `.env.staging` (mode 600, never in
  Git or images), passed only to the sending service.
  - Use a **send-only** key (Postmark server token; SES IAM user restricted to
    `ses:SendEmail` on the one identity).
  - Rotate it on any suspected exposure; it goes on the incident checklist in the runbook.
- **Least-privileged sending path.** Today no app container has internet egress (internal
  Docker networks). Keep it that way for `api`, `admin-api`, `web` and `db`.
  - **New `mailer` service:** the same image as the worker, on the `backend` network plus
    one egress-capable network. It reads unsent outbox rows as a DB role that can only
    `SELECT`/`UPDATE` `email_outbox`, then calls the provider's HTTPS API.
  - **Stricter option:** host-level egress rules (ufw/nftables) limiting that container to
    port 443.
- **Tokens at rest.** Outbox rows currently hold the raw one-time link in `data`. Once mail
  is real:
  - Mark rows sent and **delete them right after sending** (not after 3 days). Keep only
    template, recipient hash, provider message ID and status for support.
  - Keep token TTLs short, and keep tokens single-use (as now).
  - Never log message bodies or links. The app's log redaction already covers tokens;
    extend it to the mailer.
- **Abuse and enumeration.**
  - Registration already returns the same response for new and existing addresses, and
    sends `account_exists` instead of revealing it.
  - Keep the existing rate limits on register, resend and forgot-password. Add a per-
    recipient send cap in the mailer (e.g. 5/hour), so the site can't be used to flood an
    inbox.
  - Consider a CAPTCHA (e.g. Cloudflare Turnstile) on registration before a public
    launch.
- **Bounces and complaints.** Suppress addresses that hard-bounce or complain, so the
  provider doesn't throttle or suspend the account.
  - Postmark: its suppression list plus a bounce webhook.
  - SES: SNS notifications.
  - A webhook endpoint would sit on the API host behind a provider-signed secret. Polling
    the provider API from the mailer avoids opening a new inbound endpoint.
- **Content.**
  - Plain-text plus simple HTML, in Mongolian, with no tracking pixels or click tracking.
    Click-tracking rewrites one-time links; turn it off at the provider.
  - Links point only to `https://safepay.dhdbot.xyz/...` (`PUBLIC_WEB_URL`).
- **Privacy.** Sending means recipient addresses go to a third-party processor (US unless
  SES Singapore). Mention this in the privacy notice before the public launch.
- **Fail closed.** If the provider is down, the outbox keeps the row and the mailer
  retries with backoff. Sign-up still succeeds and "resend" works later. Nothing is lost
  or sent twice: each row has an idempotency key (the outbox row ID, passed to the
  provider where supported).

## Implementation steps (after a provider is approved)

1. 🔒 **Choose the provider and create the account.** You create it; I never hold the
   account password. Request production access where required (Postmark approval, SES
   sandbox exit).
2. 🔒 **DNS.** Snapshot the zone, add the DKIM, Return-Path/SPF and DMARC records for the
   sending subdomain, then verify in the provider dashboard and with `dig`.
3. **Code (new PR, CI-tested; no live change):**
   - `EMAIL_DELIVERY=simulated|provider` setting, default `simulated`. Startup refuses
     `provider` without a key, and staging refuses it while the key is a placeholder.
   - Outbox columns: `status`, `attempts`, `sent_at`, `provider_message_id`; plus a
     migration and a least-privileged `safepay_mailer` role.
   - Mailer loop: claim rows with `FOR UPDATE SKIP LOCKED`, send, mark sent, delete the
     link data, retry with backoff, and apply the per-recipient cap.
   - Provider adapter with a fake used in tests. Tests cover:
     - no request is made in `simulated` mode;
     - no token appears in logs;
     - retries and idempotency;
     - the per-recipient cap.
   - Mongolian email templates (text + HTML).
   - Compose: a `mailer` service with egress, and nothing else gains egress. CI asserts
     that `api`, `admin-api`, `web` and `db` still have no egress.
   - Runbook: key rotation, bounce handling and switching back to `simulated`.
4. 🔒 **Deploy with `EMAIL_DELIVERY=provider` while still `SITE_ACCESS=private`.**
   Verify:
   - sign-up and password reset end-to-end with testers' real inboxes;
   - SPF/DKIM/DMARC show `pass` in a received message's headers;
   - the mail does not land in spam (Gmail, Outlook, Yahoo, plus a local provider such as
     mail.mn if relevant).
5. 🔒 **Only then switch `SITE_ACCESS=public`** (runbook §9a).

## Decisions for you

1. Provider: **Postmark** (recommended), **SES** (cheapest, more setup) or another.
2. Sending address: e.g. `no-reply@mail.safepay.dhdbot.xyz`, and a monitored `Reply-To`.
3. Whether to add a CAPTCHA to registration before the public launch.
