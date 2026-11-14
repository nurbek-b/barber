#!/usr/bin/env bash
# Runs on the server (called by CI over SSH, or by hand):
#   IMAGE_TAG=<git sha> /opt/barber/scripts/deploy.sh
# Pulls the new images, applies migrations, then restarts the services. Migrations are
# written to be backward compatible with the previous release (expand → migrate → contract).
set -euo pipefail

cd "$(dirname "$0")/.."
: "${IMAGE_TAG:?IMAGE_TAG is required}"
export IMAGE_TAG
COMPOSE=(docker compose -f compose.prod.yml --env-file .env)

echo "→ pulling ${IMAGE_TAG}"
"${COMPOSE[@]}" pull api bot worker nginx

echo "→ starting data services"
"${COMPOSE[@]}" up -d postgres redis

echo "→ migrating"
"${COMPOSE[@]}" --profile migrate run --rm migrate

echo "→ switching services"
"${COMPOSE[@]}" up -d --remove-orphans api bot worker nginx certbot

echo "→ waiting for health"
for _ in $(seq 1 30); do
  if "${COMPOSE[@]}" exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready', timeout=2)" 2>/dev/null; then
    echo "✓ ${IMAGE_TAG} is up"
    sed -i.bak "s/^IMAGE_TAG=.*/IMAGE_TAG=${IMAGE_TAG}/" .env && rm -f .env.bak
    docker image prune -f >/dev/null
    exit 0
  fi
  sleep 2
done
echo "✗ api did not become ready" >&2
"${COMPOSE[@]}" logs --tail=100 api >&2
exit 1
