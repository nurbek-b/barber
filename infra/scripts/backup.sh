#!/usr/bin/env bash
# Nightly logical backup (cron: 0 3 * * * /opt/barber/scripts/backup.sh). Keeps 14 days.
set -euo pipefail
cd "$(dirname "$0")/.."
source .env
mkdir -p backups
file="backups/barber-$(date +%Y%m%d-%H%M).sql.gz"
docker compose -f compose.prod.yml --env-file .env exec -T postgres \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner | gzip > "$file"
find backups -name 'barber-*.sql.gz' -mtime +14 -delete
echo "backup: $file"
