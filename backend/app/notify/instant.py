"""Send Telegram notifications created by a request right away, not on the next worker tick.

The outbox stays the source of truth (retries, rate limits, dead letters, at-most-once via
SKIP LOCKED + status); this only drains the rows a request just created, *before* the
response starts — on Cloud Run the CPU is throttled once the response has been sent.
If sending fails or is slow, the worker's minute tick picks the rows up as before.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import event
from sqlalchemy.orm import Session
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.models import TelegramOutbox
from app.worker.outbox import Sender, drain_outbox

logger = structlog.get_logger(__name__)

OUTBOX_IDS = "outbox_ids"
SEND_TIMEOUT_SECONDS = 3.0


@event.listens_for(Session, "after_flush")
def _collect_new_outbox_rows(session: Session, _flush_context: Any) -> None:
    ids = session.info.get(OUTBOX_IDS)
    if ids is None:
        return  # session not bound to a request (worker, CLI)
    ids.extend(obj.id for obj in session.new if isinstance(obj, TelegramOutbox))


def track_outbox(session_info: dict[str, Any], scope_state: dict[str, Any]) -> None:
    """Bind a request's DB session to the request so its new outbox rows can be sent."""
    ids: list[uuid.UUID] = scope_state.setdefault(OUTBOX_IDS, [])
    session_info[OUTBOX_IDS] = ids


async def send_now(app_state: Any, ids: list[uuid.UUID]) -> None:
    sender: Sender | None = getattr(app_state, "outbox_sender", None)
    maker = getattr(app_state, "sessionmaker", None)
    if not ids or sender is None or maker is None:
        return
    try:
        await asyncio.wait_for(
            drain_outbox(maker, sender, datetime.now(UTC), batch=len(ids), ids=list(ids)),
            SEND_TIMEOUT_SECONDS,
        )
    except Exception:  # never fail the request: the worker retries these rows
        logger.warning("instant_send_failed", count=len(ids), exc_info=True)
    finally:
        ids.clear()


class InstantOutboxMiddleware:
    """Drains the request's new outbox rows just before the response starts."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                ids = scope.get("state", {}).get(OUTBOX_IDS)
                if ids:
                    await send_now(scope["app"].state, ids)
            await send(message)

        await self.app(scope, receive, send_wrapper)
