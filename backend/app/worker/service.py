"""Worker as an HTTP service for Cloud Run (`docker-entrypoint.sh worker-http`).

Cloud Run services cannot run a background loop cheaply, so the cron jobs of
`WorkerSettings` are exposed as endpoints and triggered by Cloud Scheduler:

    POST /tasks/tick   every minute — outbox + reminders (+ outbox again for fresh reminders)
    POST /tasks/bonus  hourly       — expiry burn, birthday credits, expiry warnings

Access control is Cloud Run IAM (the service is deployed with --no-allow-unauthenticated
and only the scheduler service account has roles/run.invoker). As defence in depth an
optional shared secret (TASKS_TOKEN) is checked too. All jobs are idempotent.
"""

from __future__ import annotations

import asyncio
import hmac
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.worker.main import bonus_jobs, queue_reminders, send_outbox, shutdown, startup


def create_worker_app(ctx: dict[str, Any] | None = None) -> FastAPI:
    token = os.environ.get("TASKS_TOKEN", "")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.ctx = ctx if ctx is not None else {}
        app.state.lock = asyncio.Lock()
        if ctx is None:
            await startup(app.state.ctx)
        try:
            yield
        finally:
            if ctx is None:
                await shutdown(app.state.ctx)

    app = FastAPI(
        title="Barbershop worker",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def authorized(request: Request) -> bool:
        return not token or hmac.compare_digest(token, request.headers.get("X-Tasks-Token", ""))

    @app.get("/health/live")
    @app.get("/api/v1/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/tasks/tick")
    async def tick(request: Request) -> JSONResponse:
        if not authorized(request):
            return JSONResponse({"ok": False}, status_code=401)
        c = request.app.state.ctx
        async with request.app.state.lock:  # overlapping scheduler calls do not double-send
            sent = await send_outbox(c)
            reminders = await queue_reminders(c)
            if reminders:
                sent += await send_outbox(c)
        return JSONResponse({"ok": True, "sent": sent, "reminders": reminders})

    @app.post("/tasks/bonus")
    async def bonus(request: Request) -> JSONResponse:
        if not authorized(request):
            return JSONResponse({"ok": False}, status_code=401)
        stats = await bonus_jobs(request.app.state.ctx)
        return JSONResponse({"ok": True, **stats})

    return app


def app_factory() -> FastAPI:
    return create_worker_app()
