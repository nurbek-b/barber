"""ARQ worker entry point: `arq app.worker.main.WorkerSettings`.

Jobs are cron-driven and idempotent, so running several workers or restarting is safe.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import LinkPreviewOptions
from arq import cron
from arq.connections import RedisSettings

from app.bot import keyboards
from app.core.config import get_settings
from app.core.db import create_engine, create_sessionmaker
from app.core.logging import configure_logging
from app.worker.bonus_jobs import run_bonus_jobs
from app.worker.outbox import RecipientBlockedError, RetryAfterError, SendError, drain_outbox
from app.worker.reminders import scan_reminders
from app.worker.revisits import scan_revisits


class AiogramSender:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send(
        self, chat_id: int, text: str, buttons: list[list[dict[str, Any]]] | None = None
    ) -> None:
        try:
            await self.bot.send_message(
                chat_id,
                text,
                reply_markup=keyboards.from_payload(buttons),
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        except TelegramRetryAfter as exc:
            raise RetryAfterError(exc.retry_after) from exc
        except TelegramForbiddenError as exc:
            raise RecipientBlockedError(str(exc)) from exc
        except TelegramBadRequest as exc:
            if "chat not found" in str(exc).lower():
                raise RecipientBlockedError(str(exc)) from exc
            raise SendError(str(exc)) from exc
        except (TelegramNetworkError, TelegramServerError) as exc:
            raise SendError(str(exc)) from exc


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    engine = create_engine(settings)
    ctx["engine"] = engine
    ctx["maker"] = create_sessionmaker(engine)
    ctx["bot"] = Bot(
        settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    ctx["sender"] = AiogramSender(ctx["bot"])


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["bot"].session.close()
    await ctx["engine"].dispose()


async def send_outbox(ctx: dict[str, Any]) -> int:
    stats = await drain_outbox(ctx["maker"], ctx["sender"], datetime.now(UTC))
    return stats.sent


async def queue_reminders(ctx: dict[str, Any]) -> int:
    return await scan_reminders(ctx["maker"], datetime.now(UTC))


async def bonus_jobs(ctx: dict[str, Any]) -> dict[str, int]:
    """Hourly: bonus expiry/birthdays/warnings and 'time for a haircut' messages."""
    now = datetime.now(UTC)
    result = await run_bonus_jobs(ctx["maker"], now)
    result["revisits"] = await scan_revisits(ctx["maker"], get_settings(), now)
    return result


class WorkerSettings:
    functions = [send_outbox, queue_reminders, bonus_jobs]  # noqa: RUF012
    cron_jobs = [  # noqa: RUF012
        cron(send_outbox, second=set(range(0, 60, 5)), run_at_startup=True, unique=True),
        cron(queue_reminders, second={0}, unique=True),
        # hourly: expiry burn, birthday credits, expiry warnings (all idempotent)
        cron(bonus_jobs, minute={5}, second={0}, unique=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 4
