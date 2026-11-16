from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.types import TelegramObject
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.handlers import build_router
from app.core.config import Settings
from app.notify.instant import OUTBOX_IDS, send_now
from app.notify.sender import AiogramSender


class DbSessionMiddleware(BaseMiddleware):
    """One DB session per update, plus settings, injected into handler kwargs."""

    def __init__(
        self,
        maker: async_sessionmaker[AsyncSession],
        settings: Settings,
        redis: Redis | None = None,
    ) -> None:
        self.maker = maker
        self.settings = settings
        self.redis = redis

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        ids: list[uuid.UUID] = []
        async with self.maker() as session:
            session.sync_session.info[OUTBOX_IDS] = ids
            data["session"] = session
            data["settings"] = self.settings
            data["redis"] = self.redis
            try:
                result = await handler(event, data)
            except BaseException:
                await session.rollback()
                raise
        bot = data.get("bot")
        if ids and isinstance(bot, Bot):
            # e.g. the admin hears about a cancel from a reminder at once, not on the next tick
            state = SimpleNamespace(outbox_sender=AiogramSender(bot), sessionmaker=self.maker)
            await send_now(state, ids)
        return result


def create_bot(settings: Settings, session: BaseSession | None = None) -> Bot:
    return Bot(
        settings.bot_token.get_secret_value(),
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )


def create_dispatcher(
    maker: async_sessionmaker[AsyncSession], settings: Settings, redis: Redis | None = None
) -> Dispatcher:
    dispatcher = Dispatcher()
    middleware = DbSessionMiddleware(maker, settings, redis)
    dispatcher.update.outer_middleware(middleware)
    dispatcher.include_router(build_router())
    return dispatcher
