# SafePay Beta v0.1 — DigitalOcean staging runbook

> **Simulation only. Staging only. Not public.** This runbook deploys the private
> staging stack (`compose.staging.yaml`) to one DigitalOcean droplet. No step here
> touches real money, real payment providers or real customer data.
>
> **Status:**
> - Nothing in this document has been run against DigitalOcean yet.
> - Every step that creates a paid resource or exposes the server is marked
>   **🔒 APPROVAL**. Do not perform it until the project owner has approved it.

Companion documents:
- [`DEPLOYMENT_AUDIT.md`](DEPLOYMENT_AUDIT.md): readiness audit, risks and blockers.
- [`STAGING.md`](STAGING.md): stack architecture, admin and tester operations.

## 0. What you get

```
 Internet ──► DigitalOcean Cloud Firewall (22 from your IP only; 80/443 from anywhere)
               └► droplet (Ubuntu 24.04, ufw with the same rules)
                    └► caddy :80/:443 — the ONLY published container
                         TLS (Let's Encrypt or internal CA) · IP allow-list · basic auth
                         └► web (Next.js) ─► api / admin-api (FastAPI) ─► db (PostgreSQL 17)
                                                worker ─┘     (internal networks, no egress)
```

| Item | Value |
|---|---|
| Droplet | Basic, Regular SSD, 2 vCPU / 4 GB / 80 GB, Ubuntu 24.04 LTS x64, region SGP1 (Singapore) |
| Public ports | 80 (redirect + ACME), 443 (HTTPS). SSH 22 only from your IP. |
| Hostname without a domain | `<ip-with-dashes>.sslip.io` (free wildcard DNS; e.g. `203-0-113-10.sslip.io`) |
| Secrets | generated **on the server** into `.env.staging` (mode 600, git-ignored) |
| Deploys | `scripts/staging-deploy.sh <tag-or-sha>`: backup, build, start, health wait, smoke test |
| Rollback | `scripts/staging-rollback.sh`: previous commit, restores the pre-deploy backup if the schema moved |
| Backups | daily `pg_dump` via a systemd timer, `age`-encrypted, pulled off the server by you |

## 1. Costs (estimate — verify on digitalocean.com/pricing before approving)

Prices are from DigitalOcean's public price list as last known and may have changed.
**Nothing has been purchased.**

| Item | Monthly (USD) | Notes |
|---|---|---|
| Droplet Basic Regular 2 vCPU / 4 GB / 80 GB SSD / 4 TB transfer | **~$24** | billed hourly up to the monthly cap |
| Droplet weekly backups (optional) | ~$4.80 | 20 % of the droplet price; daily backups ~30 % |
| Cloud Firewall | $0 | |
| Monitoring + alert policies | $0 | |
| Reserved IP (optional, keeps the sslip.io hostname if the droplet is rebuilt) | $0 while assigned | charged when left unassigned |
| Snapshots (optional, manual) | ~$0.06 / GB-month | e.g. a 10 GB snapshot ≈ $0.60 |
| Spaces object storage (optional off-site backups) | ~$5 | not needed if you pull backups to your own machine |
| TLS (Let's Encrypt), sslip.io hostname | $0 | |
| **Typical total** | **~$24–30** | droplet plus optional weekly backups |

Bandwidth for a closed beta stays far below the included 4 TB.

## 2. Before you start (on your own computer)

1. Find your public IPv4 address, for example by searching "what is my IP". SSH will
   only be allowed from it. Below it is written `YOUR_IP` (as a CIDR: `YOUR_IP/32`).
2. Create a dedicated SSH key. The private key never leaves your computer and is never
   shared:
   ```bash
   ssh-keygen -t ed25519 -C "safepay-staging" -f ~/.ssh/safepay_staging
   ```
3. Create the backup encryption key **on your computer, not on the server**. Keep
   `safepay-backup-key.txt` offline, for example in your password manager:
   ```bash
   age-keygen -o safepay-backup-key.txt      # prints "Public key: age1..."
   ```
4. Decide the release to deploy: a reviewed tag or commit SHA on `main`. It must contain
   this deployment tooling, so merge this PR first.

## 3. DigitalOcean resources — 🔒 APPROVAL (creates billable resources)

### Control panel

1. **Settings → Security → SSH Keys → Add SSH Key.** Paste the contents of
   `~/.ssh/safepay_staging.pub` (the `.pub` file only).
2. **Create → Droplets:**
   - **Region:** Singapore · **SGP1**
   - **Image:** Ubuntu **24.04 (LTS) x64**
   - **Size:** Basic → Regular (SSD) → **$24/mo, 2 vCPU / 4 GB / 80 GB**
   - **Authentication:** SSH key `safepay-staging`. No password.
   - **Advanced:** leave IPv6 **off** (the sslip.io hostname is IPv4); enable
     **Monitoring**.
   - **Backups:** optional (weekly).
   - **Hostname:** `safepay-staging` · **Tags:** `safepay-staging`
3. **Networking → Firewalls → Create Firewall**, named `safepay-staging-fw`:

   | Inbound rule | Protocol | Port | Sources |
   |---|---|---|---|
   | SSH | TCP | 22 | `YOUR_IP/32` only |
   | HTTP | TCP | 80 | All IPv4, All IPv6 |
   | HTTPS | TCP | 443 | All IPv4, All IPv6 |

   - Keep the default outbound rules (all).
   - Apply the firewall to the tag `safepay-staging`.
4. Optional: **Networking → Reserved IPs**, assign one to the droplet and use that
   address everywhere below.
5. Optional: **Monitoring → Create alert policy** for CPU > 80 %, memory > 85 % and
   disk > 80 % for 5 minutes, sent to your email.

### Equivalent `doctl` commands

Use these if you prefer the CLI (authenticate with `doctl auth init`).

```bash
doctl compute ssh-key import safepay-staging --public-key-file ~/.ssh/safepay_staging.pub
doctl compute droplet create safepay-staging --region sgp1 --image ubuntu-24-04-x64 \
  --size s-2vcpu-4gb --ssh-keys "$(doctl compute ssh-key list --format ID,Name --no-header | awk '/safepay-staging/{print $1}')" \
  --enable-monitoring --tag-names safepay-staging --wait
doctl compute firewall create --name safepay-staging-fw --tag-names safepay-staging \
  --inbound-rules "protocol:tcp,ports:22,address:YOUR_IP/32 protocol:tcp,ports:80,address:0.0.0.0/0,address:::/0 protocol:tcp,ports:443,address:0.0.0.0/0,address:::/0" \
  --outbound-rules "protocol:tcp,ports:all,address:0.0.0.0/0,address:::/0 protocol:udp,ports:all,address:0.0.0.0/0,address:::/0 protocol:icmp,address:0.0.0.0/0,address:::/0"
doctl compute droplet get safepay-staging --format PublicIPv4     # -> DROPLET_IP
```

From here on, `DROPLET_IP` is the droplet's public IPv4 address, for example
`203.0.113.10`. `HOST` is the same address with dashes plus `.sslip.io`, for example
`203-0-113-10.sslip.io`.

## 4. Harden the server (first login, as root)

```bash
# From your computer:
scp -i ~/.ssh/safepay_staging scripts/vps-bootstrap.sh root@DROPLET_IP:/root/
ssh -i ~/.ssh/safepay_staging root@DROPLET_IP
# On the droplet:
bash /root/vps-bootstrap.sh --ssh-from YOUR_IP/32      # asks for the deploy user's sudo password
```

The script does the following:
- creates the `deploy` user;
- SSH: keys only, no root login;
- ufw: 22 from `YOUR_IP` only, 80/443 open;
- unattended security upgrades, 2 GB swap, Docker Engine and Compose, Docker log
  rotation.

**Keep the root session open.** In a second terminal, check that this works:

```bash
ssh -i ~/.ssh/safepay_staging deploy@DROPLET_IP
docker version && docker compose version && sudo ufw status
```

Only then close the root session. If you lock yourself out, use the droplet's
**Access → Droplet Console** in the control panel.

## 5. Get the code (as `deploy`)

The repository is fetched with a read-only **deploy key** generated on the server. Its
private half never leaves the droplet.

```bash
ssh-keygen -t ed25519 -N "" -C "safepay-staging-deploy" -f ~/.ssh/github_deploy
cat ~/.ssh/github_deploy.pub
```

1. In GitHub, open **Jrelend/safepay → Settings → Deploy keys → Add deploy key**.
2. Paste the public key and leave **Allow write access** unticked.

```bash
cat >> ~/.ssh/config <<'EOF'
Host github.com
  IdentityFile ~/.ssh/github_deploy
  IdentitiesOnly yes
EOF
ssh -T git@github.com     # check the fingerprint against GitHub's published SSH key fingerprints, then type yes
git clone git@github.com:Jrelend/safepay.git ~/safepay && cd ~/safepay
```

## 6. Configure secrets (on the droplet)

```bash
cd ~/safepay
scripts/staging-init-secrets.sh HOST          # e.g. 203-0-113-10.sslip.io; prints the basic-auth password ONCE
nano .env.staging
```

The init script generates five random database passwords and the bcrypt basic-auth
hash. In `.env.staging`, set:

| Variable | Set to |
|---|---|
| `STAGING_DOMAIN` | `HOST` (already set by the script) |
| `CADDY_TLS` | `internal` for the first smoke test; then your email address for a Let's Encrypt certificate |
| `ALLOWED_IPS` | testers' networks, or keep `"0.0.0.0/0 ::/0"` and rely on basic auth |
| `ADMIN_ALLOWED_IPS` | `"YOUR_IP/32"`; the admin area is unreachable from anywhere else |
| `BACKUP_AGE_RECIPIENT` | the `age1...` public key from step 2.3 |

Store the basic-auth password and a copy of `.env.staging` in your password manager.
Never commit `.env.staging`, and never paste it into chat, issues or PRs.

Then check the file and the hostname:

```bash
stat -c %a .env.staging                     # must print 600
scripts/staging-check-dns.sh                # HOST must resolve to this droplet
```

## 7. Deploy — 🔒 APPROVAL (starts serving on ports 80/443)

```bash
scripts/staging-deploy.sh <tag-or-commit-sha>
```

The script runs these steps in order and stops on the first failure:

1. **Preflight:** env file mode, clean checkout, no real-payment mode, DNS check
   (with Let's Encrypt), warning if backups are unencrypted.
2. **Backup:** skipped on the very first deploy.
3. **Check out:** the commit, detached.
4. **Build:** `safepay-api:<sha12>` and `safepay-web:<sha12>`.
5. **Start:** `docker compose up -d`, with migrations run as `safepay_migrator`.
6. **Wait:** until every service is healthy.
7. **Smoke test:**
   - only Caddy publishes ports, 80/443 only;
   - HTTP redirects to HTTPS, and HTTPS returns 401 for basic auth;
   - `/ready` passes (database, migrations at head, least-privileged role);
   - payments are simulation-only;
   - automatic release is disabled.

Re-run the smoke test at any time with `scripts/staging-smoke.sh`.

From your computer, check the site. Expect a basic-auth prompt, then the Mongolian
landing page with the "Туршилтын орчин" banner.

```bash
curl -sI http://HOST | head -1                         # 308 -> https
curl -skI https://HOST | head -1                       # 401 (basic auth)
```

**Switch to a trusted certificate:**
1. Set `CADDY_TLS=you@example.com` in `.env.staging`.
2. Run:
   ```bash
   scripts/staging-check-dns.sh
   docker compose -f compose.staging.yaml --env-file .env.staging up -d caddy
   scripts/staging-smoke.sh                               # now validates the certificate
   ```

If issuance fails, check `docker compose ... logs caddy`. Let's Encrypt rate limits
apply, so do not retry in a tight loop. Fall back to `CADDY_TLS=internal` meanwhile.

### First admin and testers

Follow [STAGING.md](STAGING.md) step 7 (`app.cli outbox`, then `app.cli grant-admin`).
Beta v0.1 sends no real email: relay verification links to testers over a trusted
channel.

## 8. Backups

Install the daily timer (as `deploy`, with sudo):

```bash
sudo cp infra/systemd/safepay-backup.service infra/systemd/safepay-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now safepay-backup.timer
systemctl list-timers safepay-backup.timer
scripts/staging-backup.sh                     # one manual run now
```

Backups are `pg_dump` files: verified readable, SHA-256 checksummed and
`age`-encrypted. Retention is 14 daily and 8 weekly copies, in `~/safepay/backups/`
on the droplet.

**Off-site copy (pull model).** The server holds no credentials for other systems.
Run this from your computer, for example weekly:

```bash
rsync -av -e "ssh -i ~/.ssh/safepay_staging" deploy@DROPLET_IP:safepay/backups/ ./safepay-backups/
```

**Restore drill.** Do this before inviting testers, and then monthly:

```bash
scp -i ~/.ssh/safepay_staging safepay-backup-key.txt deploy@DROPLET_IP:/tmp/k.txt
ssh -i ~/.ssh/safepay_staging deploy@DROPLET_IP
cd ~/safepay && AGE_IDENTITY_FILE=/tmp/k.txt scripts/staging-restore.sh backups/daily/<file>.dump.age
shred -u /tmp/k.txt && scripts/staging-wait.sh && scripts/staging-smoke.sh
```

## 9. Update and rollback

Update to a new reviewed release:

```bash
cd ~/safepay && scripts/staging-deploy.sh <new-tag-or-sha>
```

Roll back to the release that was live before the last deploy:

```bash
cd ~/safepay && scripts/staging-rollback.sh
```

How rollback behaves:
- **Database schema unchanged:** the data is kept, and the previous images are reused
  (no rebuild).
- **The deploy applied a migration:** migrations refuse to downgrade over data, so the
  rollback restores the backup taken just before that deploy. It warns that everything
  written after that backup is lost, takes a safety backup of the current state first,
  and asks you to type `rollback`.
- **Encrypted backup:** prefix the command with `AGE_IDENTITY_FILE=/tmp/k.txt`.
- **Specific release:** `scripts/staging-rollback.sh --to <tag-or-sha>`.

Deploy history (time, from/to commit, backup used, schema) is kept in
`~/safepay/.deploy/history`.

## 10. Recovery

| Situation | Action |
|---|---|
| A container crashed | Restarts automatically (`restart: unless-stopped`). Investigate with `docker compose -f compose.staging.yaml --env-file .env.staging ps -a` and `logs --tail 200 <service>`. |
| Droplet rebooted | Docker starts on boot and brings the stack back. Verify with `scripts/staging-wait.sh && scripts/staging-smoke.sh`. |
| Bad deploy | `scripts/staging-rollback.sh` |
| Corrupted or wrong data | `scripts/staging-backup.sh` (keep the evidence), then `scripts/staging-restore.sh <backup>` |
| Disk filling up | `df -h`, `docker system df`; `docker image prune -a --filter "until=168h"` removes old release images (rollback then rebuilds). |
| Lost SSH access (your IP changed) | Control panel → droplet → **Access → Droplet Console**, then `sudo ufw allow from NEW_IP/32 to any port 22 proto tcp`. Also update the Cloud Firewall rule. |
| Droplet destroyed | Create a new droplet (§3, reuse the Reserved IP to keep `HOST`), then §4–§6. Restore `.env.staging` from your password manager, deploy the same tag (§7), restore the latest off-site backup (§8). Caddy obtains a new certificate automatically. |
| Suspected compromise | Power off the droplet from the control panel. Take a snapshot for forensics. Rotate the basic-auth password, all DB passwords, the admin TOTP (`app.cli reset-admin-credentials`) and the GitHub deploy key. Rebuild from a clean droplet. |

## 11. Tear down — 🔒 APPROVAL (irreversible)

```bash
docker compose -f compose.staging.yaml --env-file .env.staging down -v   # deletes the database volume
```

Then destroy the droplet, firewall, reserved IP and snapshots in the control panel,
and remove the deploy key from GitHub.
