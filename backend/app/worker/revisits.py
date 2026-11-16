"""'Time for a haircut': remind a client to come again N days after their last visit.

Runs hourly (with the bonus jobs). One message per visit (bookings.revisit_nudged_at), only
when the client has nothing booked ahead, only 10:00-20:00 salon time, and only for visits
in a two-week window after the N days — turning the feature on does not message everyone
who has not been in for years.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.texts import t
from app.core.config import Settings
from app.models import Barber, Booking, Client, SalonSettings, TelegramOutbox, User
from app.models.enums import ACTIVE_BOOKING_STATUSES, BookingKind, BookingStatus

logger = structlog.get_logger(__name__)

SEND_HOURS = range(10, 20)  # local time
CATCH_UP = timedelta(days=14)


def book_button(settings: Settings, lang: str) -> list[list[dict[str, str]]]:
    label = t("revisit_book", lang)
    if settings.miniapp_url:
        return [[{"text": label, "web_app": settings.miniapp_url}]]
    link = f"https://t.me/{settings.bot_username}/{settings.miniapp_short_name}?startapp=book"
    return [[{"text": label, "url": link}]]


async def scan_revisits(
    maker: async_sessionmaker[AsyncSession], settings: Settings, now: datetime
) -> int:
    created = 0
    async with maker() as session:
        for salon in (await session.execute(select(SalonSettings))).scalars().all():
            days = salon.revisit_after_days
            if not days or now.astimezone(ZoneInfo(salon.timezone)).hour not in SEND_HOURS:
                continue
            last = (
                select(Booking)
                .distinct(Booking.client_id)
                .where(
                    Booking.branch_id == salon.branch_id,
                    Booking.kind == BookingKind.APPOINTMENT,
                    Booking.status == BookingStatus.COMPLETED,
                    Booking.client_id.is_not(None),
                )
                .order_by(Booking.client_id, Booking.start_at.desc())
                .subquery()
            )
            due_from = now - timedelta(days=days)
            upcoming = (
                select(Booking.id)
                .where(
                    Booking.client_id == last.c.client_id,
                    Booking.status.in_(ACTIVE_BOOKING_STATUSES),
                    Booking.start_at > now,
                )
                .correlate(last)
            )
            rows = (
                await session.execute(
                    select(last.c.id, Client, User, Barber.name)
                    .join(Client, Client.id == last.c.client_id)
                    .join(User, User.id == Client.user_id)
                    .join(Barber, Barber.id == last.c.barber_id)
                    .where(
                        last.c.start_at <= due_from,
                        last.c.start_at > due_from - CATCH_UP,
                        last.c.revisit_nudged_at.is_(None),
                        Client.is_blocked.is_(False),
                        User.bot_blocked.is_(False),
                        ~exists(upcoming),
                    )
                )
            ).all()
            for booking_id, client, user, barber_name in rows:
                claimed = await session.execute(
                    update(Booking)
                    .where(Booking.id == booking_id, Booking.revisit_nudged_at.is_(None))
                    .values(revisit_nudged_at=now)
                    .returning(Booking.id)
                )
                if claimed.scalar_one_or_none() is None:
                    continue  # another worker got there first
                session.add(
                    TelegramOutbox(
                        chat_id=user.telegram_id,
                        template_key="revisit_client",
                        language=client.language,
                        booking_id=booking_id,
                        payload={
                            "name": (client.name or "").split(" ")[0],
                            "barber": barber_name,
                            "days": days,
                            "buttons": book_button(settings, client.language),
                        },
                        dedupe_key=f"revisit:{booking_id}",
                    )
                )
                created += 1
        await session.commit()
    if created:
        logger.info("revisit_nudges_queued", count=created)
    return created
