#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# Check that STAGING_DOMAIN and STAGING_API_DOMAIN resolve to THIS server before Caddy
# asks Let's Encrypt for certificates (a wrong record wastes the CA's rate limit and
# leaves HTTPS down). Read-only: it never changes DNS.
#   scripts/staging-check-dns.sh [expected-public-ipv4]
# Without an argument the droplet's public IPv4 comes from the DigitalOcean metadata
# service (only reachable from the droplet itself).
# With `dig` installed (bootstrap installs it) it also checks CAA records, which can
# forbid Let's Encrypt for the whole parent domain.
set -euo pipefail
. "$(dirname "$0")/staging-lib.sh"
load_env

expected="${1:-}"
if [[ -z "$expected" ]]; then
  expected="$(curl -fsS --noproxy '*' --max-time 3 \
    http://169.254.169.254/metadata/v1/interfaces/public/0/ipv4/address 2>/dev/null || true)"
fi
[[ "$expected" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] \
  || { echo "cannot determine this server's public IPv4; pass it as an argument" >&2; exit 1; }

check_name() {
  local domain="$1" v4 v6
  [[ "$domain" =~ ^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$ ]] \
    || { echo "'$domain' is not a valid lower-case DNS hostname" >&2; return 1; }
  case "$domain" in
    *.example.mn|*.example.com|*.example|*.test|*.invalid|*.localhost|localhost)
      echo "'$domain' is a placeholder/reserved name; set the real hostname" >&2; return 1 ;;
  esac
  mapfile -t v4 < <(getent ahostsv4 "$domain" | awk '{print $1}' | sort -u)
  [[ ${#v4[@]} -gt 0 ]] || { echo "$domain has no A record (yet?)" >&2; return 1; }
  if [[ ${#v4[@]} -ne 1 || "${v4[0]}" != "$expected" ]]; then
    echo "$domain resolves to ${v4[*]}, expected only $expected" >&2
    echo "  (a CDN/proxy in front, e.g. Cloudflare's orange cloud, must be off: DNS only)" >&2
    return 1
  fi
  # A stray AAAA record pointing elsewhere makes the ACME challenge fail over IPv6.
  mapfile -t v6 < <(getent ahostsv6 "$domain" | awk '{print $1}' | grep -v '^::ffff:' | sort -u || true)
  if [[ ${#v6[@]} -gt 0 ]]; then
    echo "warning: $domain also has AAAA ${v6[*]}; it must reach this server too (or remove it)" >&2
  fi
  echo "dns ok: $domain -> $expected"
}

# RFC 8659: the CAA set that applies is the first one found walking up from the name.
check_caa() {
  local name="$1" records
  command -v dig >/dev/null || { echo "note: dig not installed; CAA not checked for $1" >&2; return 0; }
  while [[ "$name" == *.* ]]; do
    records="$(dig +short CAA "$name" 2>/dev/null | grep -iE ' issue ' || true)"
    if [[ -n "$records" ]]; then
      if grep -qi 'letsencrypt.org' <<<"$records"; then
        echo "caa ok: $1 (Let's Encrypt allowed by CAA at $name)"; return 0
      fi
      echo "CAA at $name does not allow letsencrypt.org; issuance for $1 will fail:" >&2
      while read -r line; do echo "  $line" >&2; done <<<"$records"
      echo "  add a CAA record on the SafePay name only (e.g. $1 CAA 0 issue \"letsencrypt.org\")" >&2
      return 1
    fi
    name="${name#*.}"
  done
  echo "caa ok: $1 (no CAA records: any CA may issue)"
}

rc=0
for domain in "$STAGING_DOMAIN" "${STAGING_API_DOMAIN:?set STAGING_API_DOMAIN}"; do
  check_name "$domain" || rc=1
  if [[ "$CADDY_TLS" != "internal" ]]; then check_caa "$domain" || rc=1; fi
done
exit "$rc"
