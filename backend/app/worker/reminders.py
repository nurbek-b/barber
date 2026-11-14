"""Reminder scanner: runs every minute, idempotent, robust to reschedules and restarts.

For each offset in salon_settings.reminder_offsets_min (e.g. 1440 and 120 minutes) a reminder
is due when now >= start_at - offset and the booking still lies in the future. A row in
booking_reminders (PK booking_id + offset) guarantees "at most once"; a reminder is skipped if
the booking was created after its moment (booking 1 hour ahead gets no 24-hour reminder).
Rescheduling deletes the booking's reminder rows, so the new time gets fresh reminders.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.models import (
    Barber,
    Booking,
    BookingReminder,
    Client,
    SalonSettings,
    TelegramOutbox,
    User,
)
from app.models.enums import BookingKind, BookingStatus
from app.services.events import format_when

logger = structlog.get_logger(__name__)


async def scan_reminders(maker: async_sessionmaker[AsyncSession], now: datetime) -> int:
    created = 0
    async with maker() as session:
        for salon in (await session.execute(select(SalonSettings))).scalars().all():
            offsets = sorted(set(salon.reminder_offsets_min or []), reverse=True)
            if not offsets:
                continue
            tz = ZoneInfo(salon.timezone)
            rows = (
                await session.execute(
                    select(Booking, Client, User, Barber)
                    .options(selectinload(Booking.services))
                    .join(Client, Client.id == Booking.client_id)
                    .join(User, User.id == Client.user_id)
                    .join(Barber, Barber.id == Booking.barber_id)
                    .where(
                        Booking.branch_id == salon.branch_id,
                        Booking.kind == BookingKind.APPOINTMENT,
                        Booking.status == BookingStatus.CONFIRMED,
                        Booking.start_at > now,
                        Booking.start_at <= now + timedelta(minutes=max(offsets)),
                        User.bot_blocked.is_(False),
                    )
                )
            ).all()
            if not rows:
                continue
            booking_ids = [row[0].id for row in rows]
            sent = {
                (item.booking_id, item.offset_min)
                for item in (
                    await session.execute(
                        select(BookingReminder).where(BookingReminder.booking_id.in_(booking_ids))
                    )
                ).scalars()
            }
            for booking, client, user, barber in rows:
                due = [
                    offset
                    for offset in offsets
                    if now >= booking.start_at - timedelta(minutes=offset)
                    and booking.created_at <= booking.start_at - timedelta(minutes=offset)
                    and (booking.id, offset) not in sent
                ]
                if not due:
                    continue
                # Worker was down past several moments: send only the nearest reminder once,
                # and mark the earlier ones as done.
                inserted = await session.execute(
                    insert(BookingReminder)
                    .values(
                        [
                            {"booking_id": booking.id, "offset_min": offset, "sent_at": now}
                            for offset in due
                        ]
                    )
                    .on_conflict_do_nothing()
                    .returning(BookingReminder.offset_min)
                )
                if not inserted.scalars().all():
                    continue  # another worker got there first
                offset = min(due)
                services = ", ".join(
                    line.name_snapshot.get(client.language) or line.name_snapshot.get("ru", "")
                    for line in booking.services
                )
                session.add(
                    TelegramOutbox(
                        chat_id=user.telegram_id,
                        template_key="reminder_client",
                        language=client.language,
                        booking_id=booking.id,
                        payload={
                            "when": format_when(booking.start_at, tz),
                            "barber": barber.name,
                            "services": services,
                            "salon": salon.name,
                            "offset_min": offset,
                        },
                        dedupe_key=f"reminder:{booking.id}:{offset}:{int(now.timestamp())}",
                    )
                )
                created += 1
        await session.commit()
    if created:
        logger.info("reminders_queued", count=created)
    return created
