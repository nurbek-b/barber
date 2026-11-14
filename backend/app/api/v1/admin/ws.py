"""Real-time events for the admin panel.

Protocol (server → client JSON):
    {"type": "hello", "server_time": "..."}                         after connect
    {"type": "event", "event": {id, type, booking_id, payload, created_at}}
    {"type": "ping"}                                                every 25 s
Client may send "ping" (text) and gets {"type": "pong"}.

Auth: the same httpOnly session cookie as the REST API, or `?ticket=` from
POST /admin/auth/ws-ticket when the socket goes to another origin (Firebase Hosting -> Cloud Run).
The Origin header must be allowed (CSWSH protection).
On reconnect the client fetches GET /admin/notifications?since=<last>.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from redis.exceptions import RedisError

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security.cookies import read_session
from app.services.admin_auth import AdminAuthService
from app.services.branches import BranchService
from app.services.events import channel
from app.services.notifications import visible_to
from app.services.permissions import Perm, has_permission

logger = structlog.get_logger(__name__)
router = APIRouter()

PING_INTERVAL_SECONDS = 25


def origin_allowed(origin: str | None, host: str | None, settings: Settings) -> bool:
    if origin is None:
        return True  # non-browser clients; browsers always send Origin for WebSockets
    if origin in settings.cors_origins:
        return True
    return host is not None and origin.split("://", 1)[-1] == host


@router.websocket("/ws")
async def admin_events(websocket: WebSocket) -> None:
    app = websocket.app
    settings: Settings = app.state.settings
    if not origin_allowed(websocket.headers.get("origin"), websocket.headers.get("host"), settings):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    async with app.state.sessionmaker() as session:
        try:
            service = AdminAuthService(session, settings)
            ticket = websocket.query_params.get("ticket")
            if ticket:
                admin, _ = await service.authenticate_ws_ticket(ticket)
            else:
                admin, _ = await service.authenticate_access(
                    read_session(websocket.cookies, settings).access
                )
            branch_id = await BranchService(session).branch_for_admin(admin)
        except AppError:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        session.expunge(admin)
    if not has_permission(admin.role, Perm.NOTIFICATIONS_READ):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    await websocket.send_json({"type": "hello", "server_time": datetime.now(UTC).isoformat()})

    pubsub = app.state.redis.pubsub()
    try:
        await pubsub.subscribe(channel(branch_id))
    except RedisError:
        logger.warning("ws_subscribe_failed", exc_info=True)
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return

    async def forward() -> None:
        loop = asyncio.get_running_loop()
        last_ping = loop.time()
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is not None and message.get("type") == "message":
                event: dict[str, Any] = json.loads(message["data"])
                if visible_to(admin, event.get("payload") or {}):
                    await websocket.send_json({"type": "event", "event": event})
            if loop.time() - last_ping >= PING_INTERVAL_SECONDS:
                await websocket.send_json({"type": "ping"})
                last_ping = loop.time()

    async def receive() -> None:
        while True:
            text = await websocket.receive_text()
            if text == "ping":
                await websocket.send_json({"type": "pong"})

    tasks = [asyncio.create_task(forward()), asyncio.create_task(receive())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(exc, WebSocketDisconnect):
                logger.warning("ws_task_failed", error=repr(exc))
    finally:
        for task in tasks:
            task.cancel()
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe()
            await pubsub.aclose()
        with contextlib.suppress(Exception):
            await websocket.close()
