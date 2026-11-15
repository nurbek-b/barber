#!/usr/bin/env bash
# One-time GCP setup for britva-barber (idempotent: safe to re-run).
#   Requires: gcloud logged in as a project Owner, Blaze plan enabled on the project.
#   Usage:    infra/cloudrun/setup.sh
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck source=/dev/null
source ./config.env
G="gcloud --project=${PROJECT_ID} --quiet"

echo "==> APIs"
$G services enable run.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com cloudscheduler.googleapis.com cloudbuild.googleapis.com \
  iam.googleapis.com storage.googleapis.com firebasehosting.googleapis.com

echo "==> Artifact Registry ${REPO}"
$G artifacts repositories describe "${REPO}" --location="${REGION}" >/dev/null 2>&1 ||
  $G artifacts repositories create "${REPO}" --repository-format=docker --location="${REGION}"

sa() { echo "$1@${PROJECT_ID}.iam.gserviceaccount.com"; }
ensure_sa() {
  $G iam service-accounts describe "$(sa "$1")" >/dev/null 2>&1 ||
    $G iam service-accounts create "$1" --display-name="$2"
}
echo "==> Service accounts"
ensure_sa barber-run "Barber Cloud Run runtime"
ensure_sa barber-scheduler "Barber Cloud Scheduler invoker"
ensure_sa barber-deploy "Barber CI deployer"

echo "==> Deployer roles (GitHub Actions)"
for role in roles/run.admin roles/artifactregistry.writer roles/cloudbuild.builds.editor \
  roles/storage.admin roles/cloudscheduler.admin roles/firebasehosting.admin \
  roles/serviceusage.serviceUsageConsumer roles/logging.viewer; do
  $G projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:$(sa barber-deploy)" \
    --role="${role}" --condition=None >/dev/null
done
for target in barber-run barber-scheduler; do
  $G iam service-accounts add-iam-policy-binding "$(sa ${target})" \
    --member="serviceAccount:$(sa barber-deploy)" --role=roles/iam.serviceAccountUser >/dev/null
done

echo "==> Media bucket gs://${MEDIA_BUCKET} (private; the API serves /media/**)"
gcloud storage buckets describe "gs://${MEDIA_BUCKET}" --project="${PROJECT_ID}" >/dev/null 2>&1 ||
  gcloud storage buckets create "gs://${MEDIA_BUCKET}" --project="${PROJECT_ID}" \
    --location="${REGION}" --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets add-iam-policy-binding "gs://${MEDIA_BUCKET}" \
  --member="serviceAccount:$(sa barber-run)" --role=roles/storage.objectAdmin >/dev/null

echo "==> Secrets"
ensure_secret() {
  $G secrets describe "$1" >/dev/null 2>&1 || $G secrets create "$1" --replication-policy=automatic
  $G secrets add-iam-policy-binding "$1" --member="serviceAccount:$(sa barber-run)" \
    --role=roles/secretmanager.secretAccessor >/dev/null
}
has_version() { $G secrets versions list "$1" --filter=state=enabled --limit=1 --format="value(name)" | grep -q .; }
# generated here: nobody needs to type them
for name in JWT_SECRET WEBHOOK_SECRET TASKS_TOKEN; do
  ensure_secret "${name}"
  has_version "${name}" || openssl rand -hex 32 | tr -d '\n' | $G secrets versions add "${name}" --data-file=-
done
# provided by you (Neon, Upstash, BotFather)
missing=()
for name in DATABASE_URL DATABASE_URL_DIRECT REDIS_URL BOT_TOKEN; do
  ensure_secret "${name}"
  has_version "${name}" || missing+=("${name}")
done

echo
if ((${#missing[@]})); then
  echo "Add the missing secrets (paste the value, then Enter and Ctrl-D — it is not echoed to logs):"
  for name in "${missing[@]}"; do
    echo "  gcloud secrets versions add ${name} --project=${PROJECT_ID} --data-file=-"
  done
  echo
  echo "  DATABASE_URL         Neon pooled string   (host contains -pooler), ?sslmode=require"
  echo "  DATABASE_URL_DIRECT  Neon direct string   (no -pooler) — used for migrations"
  echo "  REDIS_URL            Upstash, rediss://default:<password>@<host>:6379"
  echo "  BOT_TOKEN            from @BotFather"
else
  echo "All secrets present."
fi
echo "==> GitHub Actions: Workload Identity Federation (no keys)"
NUMBER="$($G projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
$G services enable iamcredentials.googleapis.com sts.googleapis.com
$G iam workload-identity-pools describe github --location=global >/dev/null 2>&1 ||
  $G iam workload-identity-pools create github --location=global --display-name="GitHub Actions"
$G iam workload-identity-pools providers describe barber-repo --location=global \
  --workload-identity-pool=github >/dev/null 2>&1 ||
  $G iam workload-identity-pools providers create-oidc barber-repo --location=global \
    --workload-identity-pool=github --display-name="${GITHUB_REPO}" \
    --issuer-uri=https://token.actions.githubusercontent.com \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition="assertion.repository=='${GITHUB_REPO}' && assertion.ref=='refs/heads/main'"
$G iam service-accounts add-iam-policy-binding "$(sa barber-deploy)" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${NUMBER}/locations/global/workloadIdentityPools/github/attribute.repository/${GITHUB_REPO}" >/dev/null
# deploy.sh reads TASKS_TOKEN to configure Cloud Scheduler
$G secrets add-iam-policy-binding TASKS_TOKEN --member="serviceAccount:$(sa barber-deploy)" \
  --role=roles/secretmanager.secretAccessor >/dev/null
echo "Provider: projects/${NUMBER}/locations/global/workloadIdentityPools/github/providers/barber-repo"
echo "(already set in .github/workflows/deploy-cloudrun.yml)"
