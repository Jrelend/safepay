#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Post-deploy checks, run ON the server after scripts/staging-wait.sh:
#   * only caddy publishes ports, and only 80/443; internal ports are closed on the host
#   * HTTP redirects to HTTPS; HTTPS answers with the basic-auth challenge
#   * with Let's Encrypt (CADDY_TLS=<email>) the certificate must validate
#   * API readiness: database, migrations at the code's head, least-privileged role
#   * simulation-only payments and disabled automatic release
#   scripts/staging-smoke.sh
set -euo pipefail
. "$(dirname "$0")/staging-lib.sh"
load_env

fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }
ok() { echo "ok: $*"; }

# 1. Published ports.
# `docker port` lists only ports actually published on the host (not merely exposed).
running="$(dc ps --services --status running)" || fail "cannot query docker compose"
for svc in db api admin-api worker web caddy; do
  grep -qx "$svc" <<<"$running" || fail "service $svc is not running"
done
for svc in $running; do
  published="$(docker port "$(dc ps -q "$svc")" | awk '{print $1}' | sort -u | tr '\n' ' ')"
  if [[ "$svc" == "caddy" ]]; then
    [[ "$published" == "443/tcp 80/tcp " ]] || fail "caddy publishes unexpected ports: '$published'"
  elif [[ -n "$published" ]]; then
    fail "$svc publishes ports: $published"
  fi
done
for port in 3000 5432 8000; do
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then fail "host port $port is open"; fi
done
ok "only caddy publishes 80/443; 3000/5432/8000 closed on the host"

# 2. Edge behaviour (connect locally, present the real hostname).
code="$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' --max-time 10 -H "Host: $STAGING_DOMAIN" http://127.0.0.1/)"
[[ "$code" == "308" ]] || fail "http:// returned $code, expected 308 redirect"
tls_opts=(-k)
if [[ "$CADDY_TLS" != "internal" ]]; then tls_opts=(); fi
code="$(curl -s --noproxy '*' "${tls_opts[@]}" -o /dev/null -w '%{http_code}' --max-time 15 \
  --resolve "$STAGING_DOMAIN:443:127.0.0.1" "https://$STAGING_DOMAIN/")" \
  || fail "HTTPS request failed (certificate not issued or not trusted yet?)"
[[ "$code" == "401" ]] || fail "https:// returned $code, expected 401 (basic auth)"
ok "HTTP->HTTPS redirect and basic auth in front of the site (tls: $CADDY_TLS)"

# 3. Readiness from inside the internal network.
dc exec -T api python -c "
import json, urllib.request
body = json.load(urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=5))
bad = {k: v for k, v in body['checks'].items() if not v['ok']}
assert body['status'] == 'ready' and not bad, body
assert {'database', 'migrations', 'db_role'} <= body['checks'].keys(), body
" || fail "api /ready is not ready"
dc exec -T admin-api python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=5)" \
  || fail "admin-api /health is not 200"
ok "api ready (database, migrations at head, least-privileged role); admin-api healthy"

# 4. Simulation-only money.
dc exec -T api python -c "
from app.core.config import get_settings
s = get_settings()
assert s.payments_simulation_only is True and s.payment_mode == 'simulation', 'not simulation-only'
assert s.app_env == 'staging', s.app_env
" || fail "API is not in simulation-only staging mode"
policy="$(db_psql -d "$POSTGRES_DB" -At -c 'SELECT auto_release_enabled FROM platform_policy')"
[[ "$policy" == "f" ]] || fail "platform_policy.auto_release_enabled is '$policy'"
dc logs worker 2>/dev/null | grep -q "automatic release: disabled" || fail "worker did not report disabled auto-release"
ok "payments simulation-only; automatic release disabled (policy + worker)"

echo "smoke ok: https://$STAGING_DOMAIN (image tag $IMAGE_TAG)"
