"""Mark visits nobody closed as no-show.

A confirmed visit that is still open `salon_settings.auto_no_show_hours` after its end gets
the no-show status with `no_show_auto` set: the client's no-show counter grows, spent bonuses,
certificates and subscription visits return — the same as a manual no-show. The admin chat is
told, and the salon switches the visit to "came" in the admin if the client was there.

Only visits that ended within the last day past the threshold are touched, so turning the
setting on never rewrites old history.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import structlog
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.models import Booking, Client, SalonSettings, TelegramOutbox
from app.models.enums import BookingKind, BookingStatus, NotificationType
from app.services.audit import Actor, AuditService
from app.services.bonus import BonusService
from app.services.events import BookingEvents, publish
from app.services.slot_cache import SlotCache
from app.services.vouchers import VoucherService

logger = structlog.get_logger(__name__)

WINDOW = timedelta(days=1)


async def mark_no_shows(
    maker: async_sessionmaker[AsyncSession], redis: Redis | None, now: datetime
) -> int:
    marked = 0
    async with maker() as session:
        rows = (
            await session.execute(
                select(Booking, SalonSettings)
                .options(selectinload(Booking.services))
                .join(SalonSettings, SalonSettings.branch_id == Booking.branch_id)
                .where(
                    Booking.kind == BookingKind.APPOINTMENT,
                    Booking.status == BookingStatus.CONFIRMED,
                    SalonSettings.auto_no_show_hours > 0,
                    Booking.end_at < now,
                    Booking.end_at > now - timedelta(hours=72) - WINDOW,
                )
                .with_for_update(of=Booking, skip_locked=True)
            )
        ).all()
        for booking, salon in rows:
            due = booking.end_at + timedelta(hours=salon.auto_no_show_hours)
            if not due <= now < due + WINDOW:
                continue
            booking.status = BookingStatus.NO_SHOW
            booking.no_show_auto = True
            client = await session.get(Client, booking.client_id) if booking.client_id else None
            if client is not None:
                client.no_show_count += 1
            await session.flush()
            await BonusService(session).refund_for_booking(booking, now)
            await VoucherService(session).release_for_booking(booking)
            AuditService(session).record(
                Actor.system(),
                "booking.auto_no_show",
                "booking",
                booking.id,
                before={"status": BookingStatus.CONFIRMED.value},
                after={"status": BookingStatus.NO_SHOW.value},
            )
            notification = await BookingEvents(session).emit(
                NotificationType.BOOKING_STATUS_CHANGED, booking, salon, auto=True
            )
            if salon.admin_chat_id:
                session.add(
                    TelegramOutbox(
                        chat_id=salon.admin_chat_id,
                        template_key="booking_auto_no_show_admin",
                        language=salon.default_language,
                        payload=notification.payload,
                        booking_id=booking.id,
                    )
                )
            await session.commit()
            await SlotCache(redis).bump([booking.barber_id])
            await publish(redis, notification)
            marked += 1
    if marked:
        logger.info("auto_no_shows_marked", count=marked)
    return marked
