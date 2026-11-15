#!/usr/bin/env bash
# Build -> migrate -> deploy api/bot/worker -> scheduler -> Firebase Hosting -> bot webhook.
#   Usage: infra/cloudrun/deploy.sh            (tag = git short sha)
#          BUILDER=docker infra/cloudrun/deploy.sh   (local/CI docker instead of Cloud Build)
#          SKIP_HOSTING=1 / SKIP_BOT_SETUP=1   to skip those steps
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck source=/dev/null
source ./config.env
ROOT="$(cd ../.. && pwd)"
G="gcloud --project=${PROJECT_ID} --quiet"
TAG="${TAG:-$(git -C "${ROOT}" rev-parse --short HEAD)}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/backend:${TAG}"
RUN_SA="barber-run@${PROJECT_ID}.iam.gserviceaccount.com"
SCHED_SA="barber-scheduler@${PROJECT_ID}.iam.gserviceaccount.com"

fb_region="$(node -e 'const r=require(process.argv[1]).hosting.rewrites.find(x=>x.run);console.log(r?r.run.region:"")' "${ROOT}/firebase.json")"
if [[ -n "${fb_region}" && "${fb_region}" != "${REGION}" ]]; then
  echo "firebase.json rewrites use ${fb_region}, config.env REGION=${REGION}: make them equal" >&2
  exit 1
fi

echo "==> Image ${IMAGE}"
if [[ "${BUILDER:-cloudbuild}" == docker ]]; then
  gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
  docker build --platform linux/amd64 -t "${IMAGE}" "${ROOT}/backend"
  docker push "${IMAGE}"
else
  $G builds submit "${ROOT}/backend" --tag "${IMAGE}" --region="${REGION}"
fi

# Commas inside values (CORS_ORIGINS) -> custom "@" delimiter for --set-env-vars
ENV_VARS="^@^ENV=production@LOG_JSON=true@COOKIE_MODE=session@COOKIE_SECURE=true"
ENV_VARS+="@MEDIA_BACKEND=gcs@MEDIA_BUCKET=${MEDIA_BUCKET}@PUBLIC_BASE_URL=${SITE_URL}"
ENV_VARS+="@MINIAPP_URL=${SITE_URL}/app/@BOT_USERNAME=${BOT_USERNAME}"
ENV_VARS+="@CORS_ORIGINS=${SITE_URL},${SITE_URL/.web.app/.firebaseapp.com}"
ENV_VARS+="@DATABASE_POOL_SIZE=5@WEB_CONCURRENCY=1"
SECRETS="DATABASE_URL=DATABASE_URL:latest,REDIS_URL=REDIS_URL:latest,BOT_TOKEN=BOT_TOKEN:latest"
SECRETS+=",WEBHOOK_SECRET=WEBHOOK_SECRET:latest,JWT_SECRET=JWT_SECRET:latest"
COMMON=(--image="${IMAGE}" --region="${REGION}" --service-account="${RUN_SA}"
  --set-env-vars="${ENV_VARS}")

job() { # name, args (comma separated), extra secrets
  $G run jobs deploy "$1" "${COMMON[@]}" --set-secrets="${SECRETS}${3:+,$3}" --args="$2" \
    --max-retries=0 --task-timeout=600
  $G run jobs execute "$1" --region="${REGION}" --wait
}

echo "==> Migrations"
job barber-migrate migrate "DATABASE_URL_DIRECT=DATABASE_URL_DIRECT:latest"

echo "==> api"
$G run deploy barber-api "${COMMON[@]}" --set-secrets="${SECRETS}" --args=api --allow-unauthenticated \
  --min-instances="${API_MIN_INSTANCES}" --max-instances=4 --concurrency=80 \
  --cpu=1 --memory=512Mi --timeout=3600 --cpu-boost
echo "==> bot"
$G run deploy barber-bot "${COMMON[@]}" --set-secrets="${SECRETS}" --args=bot --allow-unauthenticated \
  --min-instances=0 --max-instances=2 --cpu=1 --memory=512Mi --timeout=60 --cpu-boost
echo "==> worker"
$G run deploy barber-worker "${COMMON[@]}" --args=worker-http --no-allow-unauthenticated \
  --set-secrets="${SECRETS},TASKS_TOKEN=TASKS_TOKEN:latest" \
  --min-instances=0 --max-instances=1 --concurrency=4 --cpu=1 --memory=512Mi --timeout=300

$G run services add-iam-policy-binding barber-worker --region="${REGION}" \
  --member="serviceAccount:${SCHED_SA}" --role=roles/run.invoker >/dev/null
API_URL="$($G run services describe barber-api --region="${REGION}" --format='value(status.url)')"
WORKER_URL="$($G run services describe barber-worker --region="${REGION}" --format='value(status.url)')"
TASKS_TOKEN="$($G secrets versions access latest --secret=TASKS_TOKEN)"

echo "==> Cloud Scheduler"
schedule() { # name, cron, path
  local verb=create headers=--headers
  if $G scheduler jobs describe "$1" --location="${REGION}" >/dev/null 2>&1; then
    verb=update headers=--update-headers
  fi
  $G scheduler jobs "${verb}" http "$1" --location="${REGION}" --schedule="$2" \
    --time-zone=Asia/Bishkek --uri="${WORKER_URL}$3" --http-method=POST \
    --oidc-service-account-email="${SCHED_SA}" --oidc-token-audience="${WORKER_URL}" \
    --attempt-deadline=240s "${headers}=X-Tasks-Token=${TASKS_TOKEN}" >/dev/null
}
schedule barber-tick "* * * * *" /tasks/tick
schedule barber-bonus "5 * * * *" /tasks/bonus

if [[ -z "${SKIP_HOSTING:-}" ]]; then
  echo "==> Firebase Hosting (admin WebSocket -> ${API_URL})"
  FIREBASE="$(command -v firebase || echo "npx --yes firebase-tools@13")"
  (cd "${ROOT}" && VITE_WS_URL="${API_URL}" ${FIREBASE} deploy --only hosting \
    --project "${PROJECT_ID}" --non-interactive ${FIREBASE_ACCOUNT:+--account "${FIREBASE_ACCOUNT}"})
fi

if [[ -z "${SKIP_BOT_SETUP:-}" ]]; then
  echo "==> Telegram webhook, commands, menu button"
  job barber-bot-setup "barber,bot-setup,--public-url,${SITE_URL}"
fi

echo
echo "Done: ${SITE_URL}/app/  ${SITE_URL}/admin/  (api ${API_URL}, image ${TAG})"
