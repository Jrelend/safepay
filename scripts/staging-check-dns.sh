#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Check that STAGING_DOMAIN resolves to THIS server before Caddy asks Let's Encrypt
# for a certificate (a wrong record wastes the CA's rate limit and leaves HTTPS down).
#   scripts/staging-check-dns.sh [expected-public-ipv4]
# Without an argument the droplet's public IPv4 comes from the DigitalOcean metadata
# service (only reachable from the droplet itself).
#
# No custom domain yet? Use a wildcard-DNS name that embeds the IP, e.g. for
# 203.0.113.10:  STAGING_DOMAIN=203-0-113-10.sslip.io   (see docs/DEPLOY_DIGITALOCEAN.md)
set -euo pipefail
. "$(dirname "$0")/staging-lib.sh"
load_env

expected="${1:-}"
if [[ -z "$expected" ]]; then
  expected="$(curl -fsS --max-time 3 \
    http://169.254.169.254/metadata/v1/interfaces/public/0/ipv4/address 2>/dev/null || true)"
fi
[[ "$expected" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] \
  || { echo "cannot determine this server's public IPv4; pass it as an argument" >&2; exit 1; }

domain="$STAGING_DOMAIN"
[[ "$domain" =~ ^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$ ]] \
  || { echo "STAGING_DOMAIN '$domain' is not a valid lower-case DNS hostname" >&2; exit 1; }
case "$domain" in
  *.example.mn|*.example.com|*.example|*.test|*.invalid|*.localhost|localhost)
    echo "STAGING_DOMAIN '$domain' is a placeholder/reserved name; set the real hostname" >&2; exit 1 ;;
esac

mapfile -t v4 < <(getent ahostsv4 "$domain" | awk '{print $1}' | sort -u)
[[ ${#v4[@]} -gt 0 ]] || { echo "$domain has no A record (yet?)" >&2; exit 1; }
if [[ ${#v4[@]} -ne 1 || "${v4[0]}" != "$expected" ]]; then
  echo "$domain resolves to ${v4[*]}, expected only $expected" >&2; exit 1
fi
# A stray AAAA record pointing elsewhere makes the ACME challenge fail over IPv6.
mapfile -t v6 < <(getent ahostsv6 "$domain" | awk '{print $1}' | grep -v '^::ffff:' | sort -u || true)
if [[ ${#v6[@]} -gt 0 ]]; then
  echo "warning: $domain also has AAAA ${v6[*]}; it must reach this server too (or remove it)" >&2
fi
echo "dns ok: $domain -> $expected"
