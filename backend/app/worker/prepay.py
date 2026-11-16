"""Cancel bookings whose required prepayment did not arrive in time.

A booking that needs prepayment is created PENDING and blocks the slot. If the client neither
paid nor tapped "I paid" within `salon_settings.prepay_timeout_min`, the slot is released:
the booking is cancelled by the system, bonuses are returned and everyone is told (the usual
cancellation messages). A pending claim keeps the booking — the salon decides.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import structlog
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.models import Booking, SalonSettings
from app.models.enums import ActorType, BookingStatus, NotificationType
from app.services.audit import Actor, AuditService
from app.services.bonus import BonusService
from app.services.events import BookingEvents, publish
from app.services.slot_cache import SlotCache
from app.services.vouchers import VoucherService

logger = structlog.get_logger(__name__)

REASON = "prepayment not received"


async def cancel_unpaid(
    maker: async_sessionmaker[AsyncSession], redis: Redis | None, now: datetime
) -> int:
    cancelled = 0
    async with maker() as session:
        rows = (
            await session.execute(
                select(Booking, SalonSettings)
                .options(selectinload(Booking.services))
                .join(SalonSettings, SalonSettings.branch_id == Booking.branch_id)
                .where(
                    Booking.status == BookingStatus.PENDING,
                    Booking.prepay_due > Booking.prepaid_amount,
                    Booking.payment_claimed_at.is_(None),
                    SalonSettings.prepay_timeout_min > 0,
                )
                .with_for_update(of=Booking, skip_locked=True)
            )
        ).all()
        for booking, salon in rows:
            if booking.created_at + timedelta(minutes=salon.prepay_timeout_min) > now:
                continue
            booking.status = BookingStatus.CANCELLED
            booking.cancelled_by = ActorType.SYSTEM
            booking.cancelled_at = now
            booking.cancel_reason = REASON
            booking.version += 1
            await session.flush()
            await BonusService(session).refund_for_booking(booking, now)
            await VoucherService(session).release_for_booking(booking)
            AuditService(session).record(
                Actor(type=ActorType.SYSTEM, id=None),
                "booking.cancel_unpaid",
                "booking",
                booking.id,
                before={"status": BookingStatus.PENDING.value},
                after={"status": BookingStatus.CANCELLED.value},
            )
            notification = await BookingEvents(session).emit(
                NotificationType.BOOKING_CANCELLED,
                booking,
                salon,
                cancelled_by=ActorType.SYSTEM.value,
                reason=REASON,
            )
            await session.commit()
            await SlotCache(redis).bump([booking.barber_id])
            await publish(redis, notification)
            cancelled += 1
    if cancelled:
        logger.info("unpaid_bookings_cancelled", count=cancelled)
    return cancelled
