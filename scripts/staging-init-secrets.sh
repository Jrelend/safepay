#!/usr/bin/env bash
# Create .env.staging from .env.staging.example with fresh random secrets.
#   scripts/staging-init-secrets.sh staging.example.mn
# Prints the generated basic-auth password ONCE; store it in your password manager.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${STAGING_ENV_FILE:-$ROOT/.env.staging}"
DOMAIN="${1:?usage: staging-init-secrets.sh <staging-domain>}"
[[ -e "$OUT" ]] && { echo "$OUT already exists; refusing to overwrite" >&2; exit 1; }

rand() { openssl rand -hex 24; }
umask 077
BASIC_PW="$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)"
BASIC_HASH="$(docker run --rm "${CADDY_IMAGE:-public.ecr.aws/docker/library/caddy:2-alpine}" \
  caddy hash-password --plaintext "$BASIC_PW")"

sed -e "s|^STAGING_DOMAIN=.*|STAGING_DOMAIN=$DOMAIN|" \
    -e "s|^BASIC_AUTH_HASH=.*|BASIC_AUTH_HASH='$BASIC_HASH'|" \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(rand)|" \
    -e "s|^SAFEPAY_MIGRATOR_PASSWORD=.*|SAFEPAY_MIGRATOR_PASSWORD=$(rand)|" \
    -e "s|^SAFEPAY_APP_PASSWORD=.*|SAFEPAY_APP_PASSWORD=$(rand)|" \
    -e "s|^SAFEPAY_SYSTEM_PASSWORD=.*|SAFEPAY_SYSTEM_PASSWORD=$(rand)|" \
    -e "s|^SAFEPAY_ADMIN_PASSWORD=.*|SAFEPAY_ADMIN_PASSWORD=$(rand)|" \
    "$ROOT/.env.staging.example" > "$OUT"
chmod 600 "$OUT"
echo "wrote $OUT (mode 600)"
echo "basic-auth user: safepay-beta  password: $BASIC_PW   <- shown once"
echo "Next: set ALLOWED_IPS / ADMIN_ALLOWED_IPS and CADDY_TLS in $OUT, then see docs/STAGING.md"
