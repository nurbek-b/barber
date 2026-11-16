#!/usr/bin/env bash
# pg_dump (custom format) streamed straight into gs://$BACKUP_BUCKET/db/<UTC timestamp>.dump
# Env: DATABASE_URL_DIRECT (secret), BACKUP_BUCKET. Auth: the job's service account token.
set -euo pipefail
: "${DATABASE_URL_DIRECT:?}" "${BACKUP_BUCKET:?}"

TOKEN="$(curl -sS -H 'Metadata-Flavor: Google' \
  http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token |
  sed -E 's/.*"access_token":"([^"]+)".*/\1/')"
NAME="db/$(date -u +%Y-%m-%d_%H%M%S).dump"

pg_dump "${DATABASE_URL_DIRECT}" --format=custom --no-owner --no-privileges |
  curl -sS --fail-with-body -X POST \
    -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/octet-stream" \
    --data-binary @- \
    "https://storage.googleapis.com/upload/storage/v1/b/${BACKUP_BUCKET}/o?uploadType=media&name=${NAME}" \
    >/dev/null
echo "backup written: gs://${BACKUP_BUCKET}/${NAME}"
