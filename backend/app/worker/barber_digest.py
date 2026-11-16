"""Morning digest for barbers: today's bookings at 9:00 salon time (hourly job, once a day)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Barber, SalonSettings, TelegramOutbox
from app.services.barber_bot import BarberBot

logger = structlog.get_logger(__name__)

DIGEST_HOUR = 9


async def send_barber_digests(maker: async_sessionmaker[AsyncSession], now: datetime) -> int:
    created = 0
    async with maker() as session:
        for salon in (await session.execute(select(SalonSettings))).scalars().all():
            local = now.astimezone(ZoneInfo(salon.timezone))
            if local.hour != DIGEST_HOUR:
                continue
            barbers = (
                (
                    await session.execute(
                        select(Barber).where(
                            Barber.branch_id == salon.branch_id,
                            Barber.is_active.is_(True),
                            Barber.telegram_chat_id.is_not(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for barber in barbers:
                agenda = await BarberBot(session).agenda(barber, local.date())
                if not agenda.items or barber.telegram_chat_id is None:
                    continue
                inserted = await session.execute(
                    insert(TelegramOutbox)
                    .values(
                        chat_id=barber.telegram_chat_id,
                        template_key="barber_morning",
                        language=salon.default_language,
                        payload={
                            "date": local.strftime("%d.%m"),
                            "count": len(agenda.items),
                            "lines": agenda.lines(salon.default_language, markup=False),
                        },
                        dedupe_key=f"digest:{barber.id}:{local.date().isoformat()}",
                    )
                    .on_conflict_do_nothing()
                    .returning(TelegramOutbox.id)
                )
                if inserted.scalar_one_or_none() is not None:
                    created += 1
        await session.commit()
    if created:
        logger.info("barber_digests_queued", count=created)
    return created
