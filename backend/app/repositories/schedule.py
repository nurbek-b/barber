from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BarberSchedule, BarberScheduleException, Booking
from app.models.enums import ACTIVE_BOOKING_STATUSES, BookingKind


class ScheduleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def weekly_for(self, barber_ids: Sequence[uuid.UUID]) -> list[BarberSchedule]:
        result = await self.session.execute(
            select(BarberSchedule)
            .where(BarberSchedule.barber_id.in_(barber_ids))
            .order_by(BarberSchedule.weekday, BarberSchedule.start_time)
        )
        return list(result.scalars())

    async def replace_weekly(self, barber_id: uuid.UUID, rows: Sequence[BarberSchedule]) -> None:
        await self.session.execute(
            delete(BarberSchedule).where(BarberSchedule.barber_id == barber_id)
        )
        self.session.add_all(rows)

    async def exceptions_for(
        self, barber_ids: Sequence[uuid.UUID], date_from: date, date_to: date
    ) -> list[BarberScheduleException]:
        result = await self.session.execute(
            select(BarberScheduleException)
            .where(
                BarberScheduleException.barber_id.in_(barber_ids),
                BarberScheduleException.date_from <= date_to,
                BarberScheduleException.date_to >= date_from,
            )
            .order_by(BarberScheduleException.date_from)
        )
        return list(result.scalars())

    async def get_exception(
        self, barber_id: uuid.UUID, exception_id: uuid.UUID
    ) -> BarberScheduleException | None:
        result = await self.session.execute(
            select(BarberScheduleException).where(
                BarberScheduleException.id == exception_id,
                BarberScheduleException.barber_id == barber_id,
            )
        )
        return result.scalar_one_or_none()

    async def overlapping_exception(
        self,
        barber_id: uuid.UUID,
        date_from: date,
        date_to: date,
        exclude_id: uuid.UUID | None = None,
    ) -> BarberScheduleException | None:
        query = select(BarberScheduleException).where(
            BarberScheduleException.barber_id == barber_id,
            BarberScheduleException.date_from <= date_to,
            BarberScheduleException.date_to >= date_from,
        )
        if exclude_id is not None:
            query = query.where(BarberScheduleException.id != exclude_id)
        result = await self.session.execute(query.limit(1))
        return result.scalar_one_or_none()

    def add(self, row: BarberScheduleException) -> None:
        self.session.add(row)

    async def delete(self, row: BarberScheduleException) -> None:
        await self.session.delete(row)


@dataclass(frozen=True, slots=True)
class BusyRow:
    booking_id: uuid.UUID
    barber_id: uuid.UUID
    kind: BookingKind
    start_at: datetime
    end_at: datetime
    blocked_until: datetime


class BookingReadRepository:
    """Read-only booking queries used by availability and schedule checks."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def active_between(
        self, barber_ids: Sequence[uuid.UUID], start: datetime, end: datetime
    ) -> list[BusyRow]:
        """Active bookings and blocks intersecting [start, end) — one query for all barbers."""
        if not barber_ids:
            return []
        result = await self.session.execute(
            select(
                Booking.id,
                Booking.barber_id,
                Booking.kind,
                Booking.start_at,
                Booking.end_at,
                Booking.blocked_until,
            )
            .where(
                Booking.barber_id.in_(barber_ids),
                Booking.status.in_(ACTIVE_BOOKING_STATUSES),
                Booking.start_at < end,
                Booking.blocked_until > start,
            )
            .order_by(Booking.barber_id, Booking.start_at)
        )
        return [BusyRow(*row) for row in result.all()]
