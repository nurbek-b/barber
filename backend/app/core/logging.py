from __future__ import annotations

import logging
import os
import sys
import time
import uuid

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_SEVERITY = {
    "debug": "DEBUG",
    "info": "INFO",
    "warning": "WARNING",
    "error": "ERROR",
    "exception": "ERROR",
    "critical": "CRITICAL",
}
_ERROR_EVENT = "type.googleapis.com/google.devtools.clouderrorreporting.v1beta1.ReportedErrorEvent"


def google_cloud_fields(
    _logger: object, method: str, event: structlog.types.EventDict
) -> structlog.types.EventDict:
    """Fields Google Cloud understands in JSON logs (Cloud Run writes stdout to Cloud Logging).

    * severity - without it every line is DEFAULT and errors can't be filtered or alerted on;
    * message  - the text shown in the log viewer;
    * an exception becomes a ReportedErrorEvent with its traceback, so Error Reporting groups
      it and can notify (``@type`` + ``stack_trace``; ``serviceContext`` names the service).
    """
    level = str(event.get("level", method)).lower()
    event["severity"] = _SEVERITY.get(level, "DEFAULT")
    event.setdefault("message", str(event.get("event", "")))
    traceback = event.get("exception")
    if traceback:
        event["@type"] = _ERROR_EVENT
        event["stack_trace"] = traceback
        event["message"] = f"{event['message']}\n{traceback}"
        event["serviceContext"] = {
            "service": os.environ.get("K_SERVICE", "barber"),
            "version": os.environ.get("K_REVISION", ""),
        }
    return event


def configure_logging(level: str = "INFO", json: bool = True) -> None:
    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    )
    cloud: list[structlog.types.Processor] = [google_cloud_fields] if json else []
    structlog.configure(
        processors=[*shared, *cloud, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=level, stream=sys.stdout, format="%(message)s")


class RequestContextMiddleware:
    """Assigns X-Request-ID, binds it to the log context and logs one line per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.log = structlog.get_logger("http")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if 0 < len(incoming) <= 64 else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        started = time.perf_counter()
        status_holder = {"status": 0}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                message.setdefault("headers", [])
                message["headers"].append((b"x-request-id", request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            if scope["type"] == "http":
                self.log.info(
                    "request",
                    method=scope.get("method"),
                    path=scope.get("path"),
                    status=status_holder["status"],
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                )


class NoSharedCacheMiddleware:
    """`Cache-Control: private, no-store` on /api/ responses that set no policy themselves.

    API answers are per-user: a CDN in front (Firebase Hosting) or a proxy must never store them.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if "cache-control" not in headers:
                    headers["Cache-Control"] = "private, no-store"
            await send(message)

        await self.app(scope, receive, send_wrapper)
