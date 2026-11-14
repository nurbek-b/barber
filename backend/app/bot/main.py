"""Webhook receiver: `uvicorn app.bot.main:app_factory --factory`.

Nginx routes /api/v1/bot/webhook here. Telegram sends the secret in
X-Telegram-Bot-Api-Secret-Token; updates are de-duplicated by update_id (Telegram retries
when a response is slow or fails), then fed to the aiogram dispatcher.
"""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from aiogram import Bot
from aiogram.types import Update
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.bot.factory import create_bot, create_dispatcher
from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_sessionmaker
from app.core.logging import RequestContextMiddleware, configure_logging
from app.core.redis import create_redis

logger = structlog.get_logger(__name__)

WEBHOOK_PATH = "/api/v1/bot/webhook"
SECRET_HEADER = "x-telegram-bot-api-secret-token"  # noqa: S105 - header name
DEDUPE_TTL_SECONDS = 24 * 3600
ALLOWED_UPDATES = ["message", "callback_query", "my_chat_member"]


def create_bot_app(
    settings: Settings | None = None, redis: Redis | None = None, bot: Bot | None = None
) -> FastAPI:
    settings = settings or get_settings()
    settings.validate_for_runtime()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        maker = create_sessionmaker(engine)
        app.state.redis = redis or create_redis(settings)
        app.state.bot = bot or create_bot(settings)
        app.state.dispatcher = create_dispatcher(maker, settings)
        try:
            yield
        finally:
            if bot is None:
                await app.state.bot.session.close()
            if redis is None:
                await app.state.redis.aclose()
            await engine.dispose()

    app = FastAPI(
        title="Barbershop bot", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.add_middleware(RequestContextMiddleware)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(WEBHOOK_PATH)
    async def webhook(request: Request) -> JSONResponse:
        expected = settings.webhook_secret.get_secret_value()
        received = request.headers.get(SECRET_HEADER, "")
        if not expected or not hmac.compare_digest(expected, received):
            return JSONResponse({"ok": False}, status_code=401)
        try:
            data: dict[str, Any] = await request.json()
            update_id = int(data["update_id"])
        except (ValueError, KeyError, TypeError):
            return JSONResponse({"ok": False}, status_code=400)

        try:
            first = await request.app.state.redis.set(
                f"tg:update:{update_id}", "1", nx=True, ex=DEDUPE_TTL_SECONDS
            )
        except RedisError:
            first = True  # better to risk a duplicate than to drop an update
        if not first:
            return JSONResponse({"ok": True, "duplicate": True})

        bot_instance: Bot = request.app.state.bot
        update = Update.model_validate(data, context={"bot": bot_instance})
        try:
            await request.app.state.dispatcher.feed_update(bot_instance, update)
        except Exception:
            # Never make Telegram retry: the update is de-duplicated anyway.
            logger.exception("bot_update_failed", update_id=update_id)
        return JSONResponse({"ok": True})

    return app


def app_factory() -> FastAPI:
    return create_bot_app()
