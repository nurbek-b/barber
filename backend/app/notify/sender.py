"""Telegram sender used by the outbox (worker) and by instant sending (API, bot)."""

from __future__ import annotations

from typing import Any

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import LinkPreviewOptions

from app.bot import keyboards
from app.worker.outbox import RecipientBlockedError, RetryAfterError, SendError


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
