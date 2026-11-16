#!/usr/bin/env bash
# Uptime check + e-mail alerts for britva-barber (idempotent: safe to re-run).
#   Usage: ALERT_EMAIL=you@example.com infra/cloudrun/monitoring.sh
# The address is passed at run time on purpose: the repository is public.
#
# Creates:
#   * e-mail notification channel
#   * uptime check  GET <SITE_URL>/api/v1/health/ready every 5 min from 3 regions
#   * alert "site is down"     — the uptime check fails for 5 minutes
#   * alert "errors in logs"   — any ERROR+ log line in Cloud Run (at most one mail per hour)
# Error details (grouped tracebacks): Cloud Console → Error Reporting.
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck source=/dev/null
source ./config.env
: "${ALERT_EMAIL:?set ALERT_EMAIL=you@example.com}"

API=https://monitoring.googleapis.com/v3/projects/${PROJECT_ID}
TOKEN="$(gcloud auth print-access-token)"
call() { # method path [json]
  local args=(-sS --fail-with-body -X "$1" "${API}$2" -H "Authorization: Bearer ${TOKEN}"
    -H "Content-Type: application/json")
  if (($# > 2)); then args+=(--data "$3"); fi
  curl "${args[@]}"
}
find_name() { # path filter-key display-name -> resource name or empty
  call GET "$1" | python3 -c '
import json, sys
key, wanted = sys.argv[1], sys.argv[2]
for item in json.load(sys.stdin).get(key, []):
    if item.get("displayName") == wanted:
        print(item["name"]); break' "$2" "$3"
}

gcloud services enable monitoring.googleapis.com --project="${PROJECT_ID}" --quiet

echo "==> e-mail channel"
CHANNEL="$(find_name /notificationChannels notificationChannels "Barber alerts")"
if [[ -z "${CHANNEL}" ]]; then
  CHANNEL="$(call POST /notificationChannels "$(python3 -c '
import json, sys
print(json.dumps({"type": "email", "displayName": "Barber alerts",
                  "labels": {"email_address": sys.argv[1]}}))' "${ALERT_EMAIL}")" |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
fi
echo "   ${CHANNEL}"

echo "==> uptime check"
HOST="${SITE_URL#https://}"
UPTIME="$(find_name /uptimeCheckConfigs uptimeCheckConfigs "Barber site")"
if [[ -z "${UPTIME}" ]]; then
  UPTIME="$(call POST /uptimeCheckConfigs "$(python3 -c '
import json, sys
print(json.dumps({
  "displayName": "Barber site",
  "monitoredResource": {"type": "uptime_url",
                        "labels": {"project_id": sys.argv[1], "host": sys.argv[2]}},
  "httpCheck": {"path": "/api/v1/health/ready", "port": 443, "useSsl": True,
                "validateSsl": True, "requestMethod": "GET"},
  "period": "300s", "timeout": "10s",
  "selectedRegions": ["EUROPE", "ASIA_PACIFIC", "USA_VIRGINIA"],
}))' "${PROJECT_ID}" "${HOST}")" | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
fi
CHECK_ID="${UPTIME##*/}"
echo "   ${UPTIME}"

policy() { # display-name json
  if [[ -n "$(find_name /alertPolicies alertPolicies "$1")" ]]; then
    echo "   exists: $1"
  else
    call POST /alertPolicies "$2" >/dev/null && echo "   created: $1"
  fi
}

echo "==> alert policies"
policy "Barber site is down" "$(python3 -c '
import json, sys
check, channel = sys.argv[1], sys.argv[2]
print(json.dumps({
  "displayName": "Barber site is down",
  "combiner": "OR",
  "conditions": [{
    "displayName": "health check failing",
    "conditionThreshold": {
      "filter": ("metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" "
                 "AND resource.type=\"uptime_url\" "
                 f"AND metric.label.check_id=\"{check}\""),
      "aggregations": [{"alignmentPeriod": "300s", "perSeriesAligner": "ALIGN_NEXT_OLDER",
                        "crossSeriesReducer": "REDUCE_COUNT_FALSE",
                        "groupByFields": ["resource.label.host"]}],
      "comparison": "COMPARISON_GT", "thresholdValue": 1, "duration": "300s",
      "trigger": {"count": 1},
    },
  }],
  "notificationChannels": [channel],
  "documentation": {"mimeType": "text/markdown",
                    "content": "https://britva-barber.web.app не отвечает. Проверьте Cloud Run → barber-api."},
}))' "${CHECK_ID}" "${CHANNEL}")"

policy "Barber errors in logs" "$(python3 -c '
import json, sys
channel = sys.argv[1]
print(json.dumps({
  "displayName": "Barber errors in logs",
  "combiner": "OR",
  "conditions": [{
    "displayName": "ERROR in Cloud Run",
    "conditionMatchedLog": {
      "filter": ("(resource.type=\"cloud_run_revision\" OR resource.type=\"cloud_run_job\") "
                 "AND severity>=ERROR")
    },
  }],
  "alertStrategy": {"notificationRateLimit": {"period": "3600s"}, "autoClose": "86400s"},
  "notificationChannels": [channel],
  "documentation": {"mimeType": "text/markdown",
                    "content": "Ошибка в бэкенде. Подробности: Cloud Console → Error Reporting."},
}))' "${CHANNEL}")"

echo
echo "Done. Error details: https://console.cloud.google.com/errors?project=${PROJECT_ID}"
