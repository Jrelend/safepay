# SafePay Beta v0.1 — deployment readiness audit (DigitalOcean staging)

| | |
|---|---|
| Date | 2026-10-16 |
| Scope | `main` @ `a04f17c`, PR #4 (UI redesign, open, CI green), this branch |
| Target | One DigitalOcean droplet (Ubuntu 24.04, 2 vCPU / 4 GB, SGP1), Docker Compose, Caddy, **private staging, simulated payments only** |

**Verdict.**
- **Ready for a private, closed staging run** once the blockers in §1 are cleared.
- **Not ready for a public or production launch.** That is out of scope, and §1 and §3
  list why.
- Nothing was deployed and no cloud resource was created.

## 1. Deployment blockers

| # | Blocker | Status / what to do |
|---|---|---|
| B1 | The deployment tooling (this branch) is not on `main`. `staging-deploy.sh` refuses commits that lack it. | Review and merge this PR, then deploy a tag of `main`. |
| B2 | PR #4 (UI/UX redesign) is not merged. Deploying `main` today ships the older UI. | Decide whether staging should show the redesign. If so, merge PR #4 first. Either order works with this tooling. |
| B3 | Hostnames: `safepay.dhdbot.xyz` (web) and `api.safepay.dhdbot.xyz` (API) in the existing `dhdbot.xyz` zone. | Add two A records, DNS only (runbook §3a). Snapshot the zone before and after so that nothing else changes. `staging-check-dns.sh` validates both names and CAA before Caddy requests certificates. The live zone could not be inspected from this sandbox (outbound DNS-over-HTTPS is blocked), so check §3a.1 for existing `safepay`/`api.safepay` records, a wildcard, CAA records and a CDN proxy. |
| B4 | No real email delivery. Verification and reset links stay in the `email_outbox` table. | Acceptable for a closed beta: the operator relays links with `app.cli outbox`. This is a blocker for any open sign-up. |
| B5 | The server bootstrap (`vps-bootstrap.sh`) and the systemd backup timer have never run on a real Ubuntu 24.04 droplet. The CI and local sandbox have no systemd, ufw or sshd. | Run them on the droplet as part of the approved setup, keeping a root session open (runbook §4). |
| B6 | Owner approval for creating the droplet (about $24/month) and for exposing ports 80/443. | Pending. Runbook steps marked 🔒. |

## 2. Audit findings by area

| Area | Finding | Rating |
|---|---|---|
| **Payments** | Hard-wired simulation: `PAYMENTS_SIMULATION_ONLY` must be `true` and `PAYMENT_MODE` must be `simulation`; the API refuses to start otherwise (tested in CI). No payment SDK or HTTP client is among the runtime dependencies. App containers sit on `internal: true` networks with **no internet egress**, verified: `ENETUNREACH` from api, admin-api, worker and web. | ✅ |
| **Ledger integrity** | Double-entry enforced inside PostgreSQL by deferred constraint triggers (every transaction balances). Ledger tables are append-only: UPDATE, DELETE and TRUNCATE are refused, even for the superuser (verified). Escrow balance is checked inside `safepay_transition_deal`. Money actions require an `Idempotency-Key`; a replayed FUND was not applied twice (verified). Automatic release is off in `platform_policy` and in the worker. | ✅ |
| **Authentication** | Argon2id password hashes. Opaque 256-bit session tokens, stored only as SHA-256. Sessions have an idle timeout and a TTL. Admins use a **separate** login (admin password + TOTP), separate session cookie, separate API process and separate DB role. **No JWTs exist**, so there is no JWT signing secret to manage. | ✅ |
| **Authorization** | Participants only: a stranger gets 404 on a deal, and an invite bound to another email is refused with 403. Role checks: a seller cannot FUND (409). A user session on `/api/admin/*` gets 401. Five PostgreSQL roles with least privilege; `/ready` fails if the API connects with more privilege than `safepay_app`. | ✅ |
| **CSRF / CORS** | Every unsafe request must carry an allowed `Origin` (or `Referer`) **and** a synchronizer token (`X-CSRF-Token` matching the hashed session value). A cross-origin POST returned 403, and a POST without the token returned 403 (both verified through Caddy). CORS is limited to `https://STAGING_DOMAIN`, and staging refuses non-https origins at startup. | ✅ |
| **Cookies** | `__Host-` prefix, `Secure`, `HttpOnly`, `SameSite` (admin: `Strict`). Staging refuses `COOKIE_SECURE=false`. | ✅ |
| **API routing** | The browser talks only to the web origin. The Next.js proxy forwards an allow-list of headers and validated path segments. `/health`, `/ready`, `/docs` and `/api/dev/*` are not reachable from outside (CI asserts 404). Caddy drops the `Authorization` header and overwrites `X-Forwarded-For`. | ✅ |
| **Migrations** | Run by a one-shot `migrate` container as `safepay_migrator`; they refuse to run as the superuser. Apps start only after `migrate` exits 0. `/ready` fails if the DB schema differs from the code. Migrations refuse destructive downgrades, so rollback across a migration needs a backup restore, which `staging-rollback.sh` automates. | ✅ |
| **Network exposure** | Only `caddy` publishes ports (80/443). db, api, admin-api, web and worker have no host ports and no egress. `staging-smoke.sh` asserts this after every deploy and in CI. | ✅ |
| **TLS / edge** | HTTP→HTTPS redirect (308), HSTS, CSP, `X-Frame-Options`, `nosniff`, no access log (URLs carry one-time tokens), IP allow-list with a stricter admin allow-list, and shared basic auth in front of everything. | ✅ |
| **Containers** | Read-only root filesystems, `cap_drop: ALL`, `no-new-privileges`, non-root users, memory and CPU limits (about 2.9 GB total on a 4 GB droplet plus 2 GB swap), `restart: unless-stopped`, json-file log rotation (10 MB × 5). | ✅ |
| **Secrets** | Generated on the server by `staging-init-secrets.sh` with `openssl rand` (192-bit DB passwords, bcrypt basic-auth hash), mode 600, git-ignored. Deploys refuse a world-readable env file. The admin password and TOTP seed are created interactively by `app.cli grant-admin`. No secret lives in Git or the images. | ✅ |
| **Backups** | Verified `pg_dump`, SHA-256, optional `age` encryption, 14 daily / 8 weekly retention, daily systemd timer. | ⚠️ Encryption is optional; the deploy warns when it is off. |
| **Admin TOTP secrets** | Stored in plaintext in `admins.totp_secret`. Anyone with a DB dump can generate admin codes, though they still need the admin password and an allow-listed IP. | ⚠️ Mitigate with `BACKUP_AGE_RECIPIENT` (always on the VPS) and backups kept off public storage. Future: encrypt at rest with a key outside the DB. |
| **API hostname** | `api.safepay.dhdbot.xyz` reverse-proxies only to the public API (`safepay_app`). The admin API, `/docs`, `/openapi.json`, `/health`, `/ready` and `/dev/*` return 404 (CI asserts this). The same IP allow-list and basic auth apply as on the web host. Caddy overwrites `X-Forwarded-For`; a spoofed value did not reach the rate limiter (verified: the limit was keyed to the real client address). The browser keeps using same-origin `/api`, so cookies stay `__Host-`. | ✅ |
| **Sharing `dhdbot.xyz` with the existing website** | The two SafePay names are subdomains of an existing site, which makes them **same-site** with it, so `SameSite` alone would not stop requests from `dhdbot.xyz`. CSRF protection does not rely on it: unsafe requests need an **exact** allowed `Origin` (`https://safepay.dhdbot.xyz`) plus the synchronizer token. A request from `Origin: https://dhdbot.xyz` returned 403 (CI asserts this). `__Host-` cookies cannot be overwritten or shadowed by cookies the parent site sets for `.dhdbot.xyz` (cookie tossing). HSTS has no `includeSubDomains`, so the parent site's HTTPS policy is untouched. SafePay sets no cookies on `dhdbot.xyz`. | ✅ |
| **Browser use of the API hostname** | Basic auth is enforced on `api.safepay.dhdbot.xyz`. Browsers send no credentials on CORS preflight, so a browser app calling that host cross-origin would fail. That is fine today (the web app uses same-origin `/api`). Revisit before building a browser client for the API host. | ℹ️ |
| **Host firewall** | Docker-published ports bypass ufw. Only Caddy publishes 80/443 by design, and the DigitalOcean Cloud Firewall filters before the droplet. | ⚠️ Keep both firewalls; never add `ports:` to other services. |

## 3. Remaining security risks (accepted for a closed staging run)

1. **Single host.** No high availability. Database and backups share a disk until you pull
   backups off-site (runbook §8).
2. **`docker` group = root.** The `deploy` user can control the host through Docker.
   Protect its SSH key.
3. **Shared basic-auth credential** for all testers. Rotate it when a tester leaves:
   update `BASIC_AUTH_HASH`, then `up -d caddy`.
4. **Base images use floating tags** (`postgres:17-alpine`, `caddy:2-alpine`,
   `node:22-alpine`, `python:3.13-slim`). Rebuilds pick up patch releases (good for
   security, less reproducible). They are not pinned by digest.
5. **CSP allows `'unsafe-inline'`**, required by Next.js without nonces.
6. **Certificate Transparency.** A Let's Encrypt certificate publishes the hostname, so
   the site can be discovered. Basic auth and the IP allow-list still gate it.
7. **No central log shipping or alerting** beyond DigitalOcean Monitoring alerts
   (recommended in the runbook). The API logs one redacted line per request; Caddy
   logs no access lines.
8. **Account squatting.** Pre-registration of someone else's email is possible (known
   from `security-review-beta.md`). There is no phone verification.
9. **SSH allowed from one IP.** If your IP changes, recovery is through the
   DigitalOcean Droplet Console (runbook §10).

## 4. Environment variables (`.env.staging`, created by `scripts/staging-init-secrets.sh`)

| Variable | Secret? | Purpose |
|---|---|---|
| `STAGING_DOMAIN` | no | Web app hostname: `safepay.dhdbot.xyz` |
| `STAGING_API_DOMAIN` | no | Public API hostname: `api.safepay.dhdbot.xyz` |
| `CADDY_TLS` | no | `internal`, or an email address for Let's Encrypt |
| `STAGING_BIND` | no | `0.0.0.0` on the VPS |
| `ALLOWED_IPS` | no | CIDRs allowed to reach the site |
| `ADMIN_ALLOWED_IPS` | no | CIDRs allowed to reach `/admin` and `/api/admin` |
| `BASIC_AUTH_USER` | no | Shared beta login name |
| `BASIC_AUTH_HASH` | **yes** (hash) | bcrypt hash of the shared beta password |
| `POSTGRES_USER`, `POSTGRES_DB` | no | Superuser name (bootstrap only), database name |
| `POSTGRES_PASSWORD` | **yes** | Superuser (init, backups, restores) |
| `SAFEPAY_MIGRATOR_PASSWORD` | **yes** | Schema owner (migrations, owner CLI) |
| `SAFEPAY_APP_PASSWORD` | **yes** | Public API runtime role |
| `SAFEPAY_SYSTEM_PASSWORD` | **yes** | Worker role |
| `SAFEPAY_ADMIN_PASSWORD` | **yes** | Admin API role |
| `BACKUP_DIR`, `BACKUP_RETENTION_DAYS`, `BACKUP_WEEKLY_RETENTION_WEEKS` | no | Backup location and retention |
| `BACKUP_AGE_RECIPIENT` | no (public key) | Encrypts backups; the private key stays offline |

These are fixed in `compose.staging.yaml` and cannot be overridden from the env file:
- `APP_ENV=staging`
- `PAYMENTS_SIMULATION_ONLY=true`
- `PAYMENT_MODE=simulation`
- `COOKIE_SECURE=true`
- `DEV_MAILBOX_ENABLED=false`
- `WORKER_AUTO_RELEASE=false`

Used by operator commands only, never stored in a file:
- `AGE_IDENTITY_FILE`: path to the backup private key, for a restore.
- `IMAGE_TAG`: written by the deploy script to `.deploy/image-tag`.

## 5. Verification performed for this branch (local rehearsal, 2026-10-16)

The full flow was rehearsed against a local Docker Engine, using a clone of the
repository as the "server". The Let's Encrypt, DNS, firewall and DigitalOcean parts
could not be exercised here (no inbound internet, no systemd, no cloud access).

| Check | Result |
|---|---|
| First deploy (no DB) → build, migrate, health, smoke | ✅ |
| Second deploy → verified pre-deploy backup, new image tag, smoke | ✅ |
| Simulated deal lifecycle through Caddy (register → verify via outbox CLI → create → invite → join → submit → accept → fund → deliver → confirm), wallet credited 750,000 ₮ | ✅ 28/28 checks |
| AuthN/AuthZ through the edge: anonymous 401, cross-origin 403, missing CSRF 403, user on admin API 401, stranger 404, invite bound to another email 403, seller FUND refused 409, idempotent FUND replay | ✅ |
| Ledger: all transactions balanced; UPDATE refused for the superuser | ✅ |
| Persistence: `compose down` + `up` → data intact; Docker daemon restart → all containers back automatically, data intact | ✅ |
| Deploy a commit with a new migration (0006) → backup at 0005 → rollback restores it, removes the 0006 table, discards post-deploy data (as warned), takes a safety backup first | ✅ |
| Rollback with an unchanged schema → data kept, previous images reused (no rebuild) | ✅ |
| `age`-encrypted backup (no plaintext visible) → restore with the identity file → newer row discarded | ✅ |
| DNS validator: reserved name refused; match ok; mismatch refused; no record refused; no IP source refused | ✅ |
| Smoke negative test: a stopped service fails the smoke test | ✅ |
| No egress from app containers (`ENETUNREACH`); `frontend` and `backend` networks `internal=true` | ✅ |
| shellcheck (all scripts), `docker compose config` with the example env | ✅ |
| API: ruff, ruff format, mypy --strict, alembic up/check/down/up, pytest | ✅ 385 passed |
| Web: eslint, tsc, vitest, `next build`, `npm audit --omit=dev` | ✅ 34 tests, 0 vulnerabilities |

Local-only accommodation:
- The sandbox intercepts TLS, so image builds used a throwaway compose override (via
  the existing `STAGING_COMPOSE_EXTRA` hook) that trusts the sandbox CA.
- The override is not in the repository. A real droplet needs nothing like it.
