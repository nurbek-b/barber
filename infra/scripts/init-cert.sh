#!/usr/bin/env bash
# First Let's Encrypt certificate (nginx can't start without one). Run once on the server
# before the first deploy, with port 80 free:  EMAIL=you@example.com ./scripts/init-cert.sh
# Renewals are handled by the certbot service in compose.prod.yml (webroot mode).
set -euo pipefail
cd "$(dirname "$0")/.."
source .env
: "${DOMAIN:?set DOMAIN in .env}" "${EMAIL:?pass EMAIL=...}"
docker compose -f compose.prod.yml --env-file .env run --rm -p 80:80 --entrypoint certbot certbot \
  certonly --standalone --non-interactive --agree-tos -m "$EMAIL" -d "$DOMAIN"
echo "certificate issued for $DOMAIN"
