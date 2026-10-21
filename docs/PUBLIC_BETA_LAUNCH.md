# Public beta launch: deployment and rollback plan

Goal: open **https://safepay.dhdbot.xyz** to external testers as a **simulated-money
demo**. Testers register, sign in without email verification, and run deals to the
end. The edge's shared basic-auth login is removed from the public pages only.

This needs:
- **[PR #6](https://github.com/Jrelend/safepay/pull/6)**: `SITE_ACCESS=public`. The web
  app opens, while the admin area and the API host keep basic auth.
- **[PR #7](https://github.com/Jrelend/safepay/pull/7)**: `BETA_DEMO_MODE=true`. Demo
  accounts can use deals without verification.

**Not needed:** no DNS change, no new cloud resources, and no real payments. Payments
stay hard-locked to simulation.

Every 🔒 step needs the owner's explicit approval.

## What was verified before launch

All on the combined tree (main + #6 + #7):

| Check | Result |
|---|---|
| GitHub CI on both PRs (API, Web, Browser E2E, Compose smoke, Staging stack) | 5/5 green on each |
| Every step of the combined CI staging job, against images built from the merged tree | all pass, including both smoke runs (public and private) and the demo on/off cycle |
| Edge + app scenario with `SITE_ACCESS=public` and `BETA_DEMO_MODE=true` (real Caddy → web → API/admin-API stack) | 70/70 checks |
| Two independent users register (no verification) and complete the full escrow: create, join, submit, accept, fund, deliver, confirm/release | ✅ |
| Cancellation, seller refund, dispute + admin decision | ✅ |
| Admin area | ✅ |
| CSRF, Origin, IDOR and rate limit (registration flood → 429) | ✅ |
| Ledger balanced, every deal created is a demo deal, policy change audited | ✅ |

**Admin area detail:**
- Without the basic-auth login: 401.
- From a non-allow-listed IP: 403, even with valid password + TOTP.
- Wrong password, a wrong code or a replayed code: 401.
- A decision without the admin CSRF token: 403.

**Migration 0006** (from #7): it upgrades and downgrades cleanly, and the patched
transition function keeps `SECURITY DEFINER`, its pinned `search_path` and owner-only
`EXECUTE`. PR #6 adds no migrations, so the two PRs merge without conflicts.

## Before you start (on the droplet)

1. **Note the live commit:** `cat ~/safepay/.deploy/history | tail -3`. This is the
   rollback target.
2. **Check the backup and admin settings:**
   - `BACKUP_AGE_RECIPIENT` is set: backups hold admin TOTP secrets.
   - `ADMIN_ALLOWED_IPS` is your own IP/32, not `0.0.0.0/0`.
3. **Check the admin account:** at least one admin exists and you can sign in with the
   admin password + TOTP, today, through the current (private) site.
4. **Keep the age identity at hand** (`AGE_IDENTITY_FILE`): rollback needs it to restore
   an encrypted backup.

## Merge 🔒

1. Squash-merge **#6** into `main`.
2. Update **#7** with the new `main` (a normal merge commit) and wait for its 5 checks
   to pass.
3. Squash-merge **#7**.
4. Optionally tag the result: `git tag -a v0.1.0-beta.2 <sha>`.

## Deploy in three stages

Each stage is reversible on its own. Stop at any failed check and use the matching
rollback.

### Stage A: new code, unchanged behaviour 🔒

```bash
cd ~/safepay
grep -E '^(SITE_ACCESS|BETA_DEMO_MODE)=' .env.staging   # expect none, or private/false
scripts/staging-deploy.sh <merged-sha>                    # backup -> build -> migrate 0006 -> smoke
```

**Expect:**
- The smoke test passes.
- The site still asks for the basic-auth login everywhere.
- `/ready` shows `beta_demo: ok`: the API setting (off) matches the DB policy (off).

**Effect on data:** migration 0006 adds `is_demo` (false) to existing users and deals.
Nothing else changes.

### Stage B: demo mode on, still private 🔒

```bash
echo 'BETA_DEMO_MODE=true' >> .env.staging
docker compose -f compose.staging.yaml --env-file .env.staging up -d migrate api
scripts/staging-wait.sh && scripts/staging-smoke.sh
docker compose -f compose.staging.yaml --env-file .env.staging exec -T db \
  psql -U postgres -d safepay -Atc 'SELECT beta_demo_enabled FROM platform_policy'   # t
```

**Behind the basic-auth login:**
- Register two fresh accounts.
- Complete one deal; cancel and refund one each.
- Open one dispute and decide it as admin.

**Effect on data:** existing (pre-demo) accounts keep requiring verification. Only
accounts registered from now on are demo accounts.

### Stage C: open the public pages 🔒

```bash
echo 'SITE_ACCESS=public' >> .env.staging
docker compose -f compose.staging.yaml --env-file .env.staging up -d caddy
scripts/staging-wait.sh && scripts/staging-smoke.sh
```

**From your computer** (not allow-listed for admin unless it is your admin IP):

```bash
curl -sI https://safepay.dhdbot.xyz/            | head -1   # 200, no WWW-Authenticate
curl -sI https://safepay.dhdbot.xyz/admin/login | head -1   # 401 (basic auth), or 403 if not allow-listed
curl -sI https://api.safepay.dhdbot.xyz/        | head -1   # 401 (API host stays private)
curl -s -o /dev/null -w '%{http_code}\n' https://safepay.dhdbot.xyz/dev/mailbox   # 404
curl -sI https://dhdbot.xyz | head -1                       # existing site unaffected
```

**In a private browser window:** register, check that the
**"DEMO — SIMULATED MONEY — NO REAL PAYMENTS"** banner is on every page, and run one
deal with a second browser.

## After launch: watch

```bash
# account growth (registration is rate-limited to 10/hour per IP; no CAPTCHA)
psql ... -Atc "SELECT date_trunc('hour', created_at), count(*) FROM users GROUP BY 1 ORDER BY 1 DESC LIMIT 24"
df -h /; docker system df                                 # disk
docker compose ... logs --since 1h api | grep -c ' 429 '  # rate-limit hits
```

The nightly encrypted backup keeps running. Check it the morning after launch.

## Rollback, fastest first

| Situation | Action | Time | Data |
|---|---|---|---|
| Unwanted traffic or abuse; want testers out | remove `SITE_ACCESS=public` (or set `private`), then `up -d caddy` | seconds | none lost |
| Stop demo sign-ups and deal access | set `BETA_DEMO_MODE=false`, then `up -d migrate api`. Unverified demo accounts can still sign in and read their deals but cannot act. The DB policy follows. | ~30 s | none lost |
| Bad code in the new release | set both of the above back first, then `scripts/staging-rollback.sh --to <previous-sha>` | minutes | **Data written after Stage A is lost.** Migration 0006 is not in the old code, so the script takes a safety backup and then restores the pre-deploy backup. It asks before restoring. |

**Notes:**
- Rolling back the code also removes the `SITE_ACCESS` switch: the previous Caddyfile
  gates the whole site again.
- Rollback never touches DNS, the firewall or cloud resources.
- **Forward fix instead of rollback:** for a problem that is only in the demo flow, the
  first two rows are enough. They keep all data and need no code change.

## Known limits accepted for the demo

- **Unverified email addresses:** no email is ever sent. Display names are
  self-chosen.
- **No CAPTCHA:** per-IP rate limits are the only brake on automated sign-ups.
- **Demo data accumulates:** it is flagged `is_demo` and never mixed with other
  accounts. Purge it, or start from a fresh database, before any real-money release.
- **Admin creation:** the operator verifies the admin's account via `app.cli outbox`,
  then runs `app.cli grant-admin`.
