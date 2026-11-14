"""Pieces shared by client and staff booking flows."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ValidationAppError
from app.domain.pricing import PriceLine, Quote, build_quote
from app.domain.slots import Interval
from app.models import BonusSettings, Booking, BookingService, Client
from app.repositories.catalog import BarberServiceRepository
from app.schemas.schedule import Slot
from app.services.availability import Audience, AvailabilityService
from app.services.bonus import BonusService
from app.services.catalog import effective_duration, effective_price

EXCLUSION_CONSTRAINT = "ex_bookings_no_overlap"
IDEMPOTENCY_INDEX = "ux_bookings_idempotency"


class SlotConflictError(ConflictError):
    code = "slot_conflict"
    message = "This time is no longer available"


def is_constraint_violation(exc: IntegrityError, name: str) -> bool:
    return name in str(exc.orig)


async def price_lines(
    session: AsyncSession, barber_id: uuid.UUID, service_ids: Sequence[uuid.UUID]
) -> list[PriceLine]:
    """Price and duration of each service for this barber, in the requested order."""
    pairs = await BarberServiceRepository(session).list_with_services([barber_id], only_active=True)
    by_service = {service.id: (link, service) for link, service in pairs}
    missing = [str(sid) for sid in service_ids if sid not in by_service]
    if missing:
        raise ValidationAppError(
            "The barber does not perform all selected services",
            code="services_not_offered",
            details={"service_ids": missing},
        )
    lines = []
    for service_id in dict.fromkeys(service_ids):
        link, service = by_service[service_id]
        lines.append(
            PriceLine(
                service_id=service.id,
                name=service.name_i18n,
                duration_min=effective_duration(link, service),
                price=effective_price(link, service),
            )
        )
    return lines


async def quote_for(
    session: AsyncSession,
    branch_id: uuid.UUID,
    barber_id: uuid.UUID,
    service_ids: Sequence[uuid.UUID],
    client: Client | None,
) -> Quote:
    lines = await price_lines(session, barber_id, service_ids)
    bonus = await session.get(BonusSettings, branch_id)
    return build_quote(
        lines,
        bonus_balance=client.bonus_balance if client else 0,
        max_spend_bp=bonus.max_spend_bp if bonus else 0,
        bonus_enabled=bool(bonus and bonus.enabled),
    )


def snapshot_services(quote: Quote) -> list[BookingService]:
    return [
        BookingService(
            service_id=line.service_id,
            name_snapshot=line.name,
            duration_min=line.duration_min,
            price=line.price,
            position=index,
        )
        for index, line in enumerate(quote.lines)
    ]


async def cap_bonus(session: AsyncSession, booking: Booking, now: datetime) -> None:
    """After the price went down, bonuses above the new subtotal are returned."""
    extra = max(booking.bonus_spent - booking.subtotal, 0)
    # set a consistent row first: the refund queries autoflush the booking
    booking.bonus_spent -= extra
    booking.total_due = booking.subtotal - booking.bonus_spent
    if extra:
        await BonusService(session).refund_for_booking(booking, now, extra)


def set_times(booking: Booking, start: datetime, duration_min: int, buffer_min: int) -> None:
    booking.start_at = start
    booking.end_at = start + timedelta(minutes=duration_min)
    booking.blocked_until = booking.end_at + timedelta(minutes=buffer_min)


async def alternatives(
    availability: AvailabilityService,
    branch_id: uuid.UUID,
    *,
    service_ids: Sequence[uuid.UUID],
    barber_id: uuid.UUID | None,
    around: datetime,
    day: date,
    now: datetime,
    audience: Audience = Audience.CLIENT,
    limit: int = 5,
    extra_busy: Mapping[uuid.UUID, Sequence[Interval]] | None = None,
) -> list[Slot]:
    """Nearest free starts on the same day (for a 409 response)."""
    try:
        result = await availability.compute(
            branch_id,
            service_ids=service_ids,
            barber_id=barber_id,
            date_from=day,
            date_to=day,
            now=now,
            audience=audience,
            extra_busy=extra_busy,
        )
    except (ValidationAppError, ConflictError):
        return []
    items = result.days[0].sorted_items() if result.days else []
    items.sort(key=lambda item: abs((item[0] - around).total_seconds()))
    return [Slot(start_at=start, barber_ids=ids) for start, ids in sorted(items[:limit])]


@dataclass(frozen=True, slots=True)
class CreatedBooking:
    booking: Booking
    created: bool  # False when returned by idempotency replay
