#!/usr/bin/env bash
# Adds the four secrets you provide (Neon x2, Upstash, BotFather) from the clipboard.
# Copy each value when asked, then press Enter: nothing is printed or kept in shell history.
#   Usage: infra/cloudrun/add-secrets.sh [NAME ...]   (default: all four)
set -uo pipefail
cd "$(dirname "$0")"
# shellcheck source=/dev/null
source ./config.env
GCLOUD="$(command -v gcloud || echo /opt/homebrew/share/google-cloud-sdk/bin/gcloud)"

describe() {
  case "$1" in
    DATABASE_URL) echo "Neon -> Connect, Connection pooling ON (host has -pooler)" ;;
    DATABASE_URL_DIRECT) echo "Neon -> Connect, Connection pooling OFF (no -pooler)" ;;
    REDIS_URL) echo "Upstash -> database -> Connect, the rediss://... URL" ;;
    BOT_TOKEN) echo "@BotFather -> /mybots -> your bot -> API Token" ;;
  esac
}

valid() { # name value -> prints reason if invalid
  local v="$2"
  case "$1" in
    DATABASE_URL)
      [[ "$v" =~ ^postgres(ql)?://[^[:space:]]+-pooler\.[^[:space:]]+$ ]] ||
        echo "expected a postgresql://... string whose host contains -pooler" ;;
    DATABASE_URL_DIRECT)
      [[ "$v" =~ ^postgres(ql)?://[^[:space:]]+$ && "$v" != *-pooler.* ]] ||
        echo "expected a postgresql://... string WITHOUT -pooler" ;;
    REDIS_URL)
      [[ "$v" =~ ^rediss://[^[:space:]]+$ ]] || echo "expected rediss://... (two s)" ;;
    BOT_TOKEN)
      [[ "$v" =~ ^[0-9]{6,12}:[A-Za-z0-9_-]{30,}$ ]] || echo "expected 123456789:AA... token" ;;
  esac
}

if [[ ! -t 0 ]]; then
  echo "Run this in an interactive terminal (Terminal.app), not from a script or chat input." >&2
  exit 1
fi

names=("$@")
((${#names[@]})) || names=(DATABASE_URL DATABASE_URL_DIRECT REDIS_URL BOT_TOKEN)
for name in "${names[@]}"; do
  while true; do
    echo
    echo "== ${name}: $(describe "${name}")"
    read -r -p "Copy it (Cmd+C), then press Enter here... " _ || exit 1
    value="$(pbpaste | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    # Neon's Connect dialog may show it as: psql 'postgresql://...'
    value="${value#psql }"
    value="${value#\'}"
    value="${value%\'}"
    reason="$(valid "${name}" "${value}")"
    if [[ -n "${reason}" ]]; then
      echo "   Not saved: ${reason}. Copy the right value and try again."
      continue
    fi
    printf '%s' "${value}" | "${GCLOUD}" secrets versions add "${name}" \
      --project="${PROJECT_ID}" --data-file=- && break
  done
done
printf '' | pbcopy
unset value
echo
echo "Done. Clipboard cleared."
