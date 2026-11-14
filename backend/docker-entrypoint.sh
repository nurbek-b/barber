#!/bin/sh
# Container roles. Cloud Run sets $PORT (8080); docker-compose uses the default 8000.
#   api | bot | worker | worker-http | migrate | <any command>
set -ef  # -f: no globbing, "*" below is literal
PORT="${PORT:-8000}"
UVICORN="uvicorn --factory --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips=* --no-server-header"

case "${1:-api}" in
  api)
    exec ${UVICORN} --workers "${WEB_CONCURRENCY:-2}" app.main:app_factory
    ;;
  bot)
    exec ${UVICORN} app.bot.main:app_factory
    ;;
  worker)
    # long-running ARQ cron worker (docker-compose / VPS)
    exec arq app.worker.main.WorkerSettings
    ;;
  worker-http)
    # Cloud Run: the same jobs as HTTP endpoints, triggered by Cloud Scheduler
    exec ${UVICORN} app.worker.service:app_factory
    ;;
  migrate)
    exec alembic upgrade head
    ;;
  *)
    exec "$@"
    ;;
esac
