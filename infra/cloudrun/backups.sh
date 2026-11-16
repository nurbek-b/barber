#!/usr/bin/env bash
# Nightly database backups (idempotent: safe to re-run).
#   gs://<project>-backups (private, objects deleted after 30 days)
#   Cloud Run job "barber-backup" (pg_dump 18 → bucket), Cloud Scheduler 03:00 Asia/Bishkek
# The app's service account may only *create* objects there — it cannot delete backups.
# Restore: see README → «Бэкапы и восстановление».
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck source=/dev/null
source ./config.env
G="gcloud --project=${PROJECT_ID} --quiet"
BUCKET="${PROJECT_ID}-backups"
RUN_SA="barber-run@${PROJECT_ID}.iam.gserviceaccount.com"
SCHED_SA="barber-scheduler@${PROJECT_ID}.iam.gserviceaccount.com"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/backup:latest"

echo "==> bucket gs://${BUCKET}"
gcloud storage buckets describe "gs://${BUCKET}" --project="${PROJECT_ID}" >/dev/null 2>&1 ||
  gcloud storage buckets create "gs://${BUCKET}" --project="${PROJECT_ID}" --location="${REGION}" \
    --uniform-bucket-level-access --public-access-prevention
LIFECYCLE="$(mktemp)"
echo '{"rule":[{"action":{"type":"Delete"},"condition":{"age":30}}]}' >"${LIFECYCLE}"
gcloud storage buckets update "gs://${BUCKET}" --lifecycle-file="${LIFECYCLE}" --quiet >/dev/null
rm -f "${LIFECYCLE}"
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${RUN_SA}" --role=roles/storage.objectCreator >/dev/null

echo "==> image ${IMAGE}"
$G builds submit backup --tag "${IMAGE}" --region="${REGION}"

echo "==> job barber-backup"
$G run jobs deploy barber-backup --image="${IMAGE}" --region="${REGION}" \
  --service-account="${RUN_SA}" --set-env-vars="BACKUP_BUCKET=${BUCKET}" \
  --set-secrets="DATABASE_URL_DIRECT=DATABASE_URL_DIRECT:latest" \
  --max-retries=1 --task-timeout=1800 --memory=1Gi
$G run jobs add-iam-policy-binding barber-backup --region="${REGION}" \
  --member="serviceAccount:${SCHED_SA}" --role=roles/run.invoker >/dev/null

echo "==> schedule 03:00 Asia/Bishkek"
URI="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/barber-backup:run"
VERB=create
$G scheduler jobs describe barber-backup --location="${REGION}" >/dev/null 2>&1 && VERB=update
$G scheduler jobs "${VERB}" http barber-backup --location="${REGION}" --schedule="0 3 * * *" \
  --time-zone=Asia/Bishkek --uri="${URI}" --http-method=POST \
  --oauth-service-account-email="${SCHED_SA}" >/dev/null

echo
echo "Done. Run one now: gcloud run jobs execute barber-backup --region=${REGION} --project=${PROJECT_ID} --wait"
