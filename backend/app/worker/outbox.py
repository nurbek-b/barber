"""Draining the Telegram outbox with retries, rate-limit handling and dead-lettering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import SalonSettings, TelegramOutbox, User
from app.models.enums import OutboxStatus
from app.notify.templates import render

logger = structlog.get_logger(__name__)

MAX_ATTEMPTS = 8
BATCH = 50


class SendError(Exception):
    """Temporary failure; the message is retried with backoff."""


class RetryAfterError(SendError):
    def __init__(self, seconds: float) -> None:
        super().__init__(f"retry after {seconds}s")
        self.seconds = seconds


class RecipientBlockedError(Exception):
    """403 from Telegram: the user blocked the bot or the chat is gone. Never retried."""


class Sender(Protocol):
    async def send(
        self, chat_id: int, text: str, buttons: list[list[dict[str, Any]]] | None = None
    ) -> None: ...


@dataclass(slots=True)
class DrainStats:
    sent: int = 0
    failed: int = 0
    dead: int = 0


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(30 * 2 ** (attempts - 1), 3600))


async def _overrides(session: AsyncSession) -> dict[str, object]:
    """Template overrides of the salon (single branch for now: merge all)."""
    merged: dict[str, object] = {}
    for templates in (
        await session.execute(select(SalonSettings.notification_templates))
    ).scalars():
        merged.update(templates or {})
    return merged


async def drain_outbox(
    maker: async_sessionmaker[AsyncSession], sender: Sender, now: datetime, batch: int = BATCH
) -> DrainStats:
    """Send due messages. Rows are locked with SKIP LOCKED, so several workers are safe."""
    stats = DrainStats()
    async with maker() as session:
        rows = (
            (
                await session.execute(
                    select(TelegramOutbox)
                    .where(
                        TelegramOutbox.status.in_((OutboxStatus.PENDING, OutboxStatus.FAILED)),
                        TelegramOutbox.send_after <= now,
                    )
                    .order_by(TelegramOutbox.send_after)
                    .limit(batch)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return stats
        overrides = await _overrides(session)
        for row in rows:
            row.attempts += 1
            try:
                text = render(row.template_key, row.language, row.payload, overrides)
                await sender.send(row.chat_id, text, row.payload.get("buttons"))
            except RecipientBlockedError as exc:
                row.status = OutboxStatus.DEAD
                row.last_error = str(exc)[:500]
                await session.execute(
                    update(User).where(User.telegram_id == row.chat_id).values(bot_blocked=True)
                )
                stats.dead += 1
            except RetryAfterError as exc:
                row.status = OutboxStatus.FAILED
                row.attempts -= 1  # rate limiting is not the message's fault
                row.send_after = now + timedelta(seconds=exc.seconds)
                row.last_error = str(exc)
                stats.failed += 1
                break  # Telegram asked us to slow down: stop this batch
            except (SendError, KeyError) as exc:
                row.last_error = str(exc)[:500]
                if row.attempts >= MAX_ATTEMPTS or isinstance(exc, KeyError):
                    row.status = OutboxStatus.DEAD
                    stats.dead += 1
                else:
                    row.status = OutboxStatus.FAILED
                    row.send_after = now + backoff(row.attempts)
                    stats.failed += 1
            else:
                row.status = OutboxStatus.SENT
                row.sent_at = now
                row.last_error = None
                stats.sent += 1
        await session.commit()
    if stats.sent or stats.failed or stats.dead:
        logger.info("outbox_drained", sent=stats.sent, failed=stats.failed, dead=stats.dead)
    return stats
