"""Barber working schedule: weekly template and date exceptions."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.domain.slots import (
    BarberSchedule as DomainSchedule,
)
from app.domain.slots import (
    ExceptionKind,
    Interval,
    LocalInterval,
    ScheduleException,
    WeeklyInterval,
    bookings_outside_schedule,
    find_local_overlap,
    find_weekly_overlap,
)
from app.models import BarberSchedule, BarberScheduleException
from app.models.enums import BookingKind
from app.repositories.catalog import BarberRepository
from app.repositories.schedule import BookingReadRepository, BusyRow, ScheduleRepository
from app.schemas.schedule import LocalIntervalIn, ScheduleExceptionIn, WeeklyIntervalIn
from app.services.audit import Actor, AuditService, snapshot
from app.services.branches import BranchService
from app.services.slot_cache import SlotCache

CONFLICT_LOOKAHEAD = timedelta(days=400)


def to_domain_weekly(rows: Sequence[BarberSchedule]) -> tuple[WeeklyInterval, ...]:
    return tuple(WeeklyInterval(row.weekday, row.start_time, row.end_time) for row in rows)


def _parse_local(raw: dict[str, Any]) -> LocalInterval:
    return LocalInterval(time.fromisoformat(str(raw["start"])), time.fromisoformat(str(raw["end"])))


def to_domain_exception(row: BarberScheduleException) -> ScheduleException:
    return ScheduleException(
        date_from=row.date_from,
        date_to=row.date_to,
        kind=ExceptionKind(row.kind.value),
        intervals=tuple(_parse_local(item) for item in row.intervals),
    )


def to_domain_schedule(
    weekly: Sequence[BarberSchedule], exceptions: Sequence[BarberScheduleException]
) -> DomainSchedule:
    return DomainSchedule(
        weekly=to_domain_weekly(weekly),
        exceptions=tuple(to_domain_exception(row) for row in exceptions),
    )


def _intervals_json(items: Sequence[LocalIntervalIn]) -> list[dict[str, str]]:
    return [
        {"start": item.start.strftime("%H:%M"), "end": item.end.strftime("%H:%M")} for item in items
    ]


@dataclass(frozen=True, slots=True)
class ScheduleChange[T]:
    value: T
    conflicting: list[BusyRow]


class ScheduleService:
    def __init__(self, session: AsyncSession, cache: SlotCache) -> None:
        self.session = session
        self.cache = cache
        self.repo = ScheduleRepository(session)
        self.barbers = BarberRepository(session)
        self.bookings = BookingReadRepository(session)
        self.branches = BranchService(session)
        self.audit = AuditService(session)

    async def _barber(self, branch_id: uuid.UUID, barber_id: uuid.UUID) -> None:
        if await self.barbers.get(branch_id, barber_id) is None:
            raise NotFoundError("Barber not found")

    async def weekly(self, branch_id: uuid.UUID, barber_id: uuid.UUID) -> list[BarberSchedule]:
        await self._barber(branch_id, barber_id)
        return await self.repo.weekly_for([barber_id])

    async def _conflicts(
        self, branch_id: uuid.UUID, barber_id: uuid.UUID, now: datetime
    ) -> list[BusyRow]:
        """Upcoming appointments that do not fit the (just updated) schedule."""
        salon = await self.branches.settings(branch_id)
        tz = ZoneInfo(salon.timezone)
        rows = [
            row
            for row in await self.bookings.active_between(
                [barber_id], now, now + CONFLICT_LOOKAHEAD
            )
            if row.kind is BookingKind.APPOINTMENT
        ]
        if not rows:
            return []
        first = rows[0].start_at.astimezone(tz).date() - timedelta(days=1)
        last = rows[-1].start_at.astimezone(tz).date()
        schedule = to_domain_schedule(
            await self.repo.weekly_for([barber_id]),
            await self.repo.exceptions_for([barber_id], first, last),
        )
        outside = set(
            bookings_outside_schedule(
                [(row.booking_id, Interval(row.start_at, row.end_at)) for row in rows],
                schedule,
                tz,
            )
        )
        return [row for row in rows if row.booking_id in outside]

    async def replace_weekly(
        self,
        branch_id: uuid.UUID,
        barber_id: uuid.UUID,
        items: Sequence[WeeklyIntervalIn],
        actor: Actor,
        now: datetime,
    ) -> ScheduleChange[list[BarberSchedule]]:
        await self._barber(branch_id, barber_id)
        domain = [WeeklyInterval(item.weekday, item.start_time, item.end_time) for item in items]
        overlap = find_weekly_overlap(domain)
        if overlap is not None:
            first, second = overlap
            raise ValidationAppError(
                "Working intervals overlap",
                code="schedule_overlap",
                details={
                    "intervals": [
                        {
                            "weekday": item.weekday,
                            "start_time": item.start.strftime("%H:%M"),
                            "end_time": item.end.strftime("%H:%M"),
                        }
                        for item in (first, second)
                    ]
                },
            )
        before = [snapshot(row) for row in await self.repo.weekly_for([barber_id])]
        rows = [
            BarberSchedule(
                barber_id=barber_id,
                weekday=item.weekday,
                start_time=item.start_time,
                end_time=item.end_time,
            )
            for item in sorted(items, key=lambda value: (value.weekday, value.start_time))
        ]
        await self.repo.replace_weekly(barber_id, rows)
        await self.session.flush()
        self.audit.record(
            actor,
            "schedule.replace",
            "barber",
            barber_id,
            before={"weekly": [{k: v for k, v in r.items() if k != "id"} for r in before]},
            after={"weekly": [{k: v for k, v in snapshot(r).items() if k != "id"} for r in rows]},
        )
        await self.session.commit()
        await self.cache.bump([barber_id])
        return ScheduleChange(rows, await self._conflicts(branch_id, barber_id, now))

    # ----- exceptions -----

    async def list_exceptions(
        self, branch_id: uuid.UUID, barber_id: uuid.UUID, date_from: date, date_to: date
    ) -> list[BarberScheduleException]:
        await self._barber(branch_id, barber_id)
        return await self.repo.exceptions_for([barber_id], date_from, date_to)

    async def _validate_exception(
        self,
        barber_id: uuid.UUID,
        data: ScheduleExceptionIn,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        local = [LocalInterval(item.start, item.end) for item in data.intervals]
        if find_local_overlap(local):
            raise ValidationAppError("Intervals overlap", code="schedule_overlap")
        clash = await self.repo.overlapping_exception(
            barber_id, data.date_from, data.date_to, exclude_id
        )
        if clash is not None:
            raise ConflictError(
                "Another exception already covers these dates",
                code="exception_overlap",
                details={
                    "exception_id": str(clash.id),
                    "date_from": clash.date_from.isoformat(),
                    "date_to": clash.date_to.isoformat(),
                },
            )

    async def create_exception(
        self,
        branch_id: uuid.UUID,
        barber_id: uuid.UUID,
        data: ScheduleExceptionIn,
        actor: Actor,
        now: datetime,
    ) -> ScheduleChange[BarberScheduleException]:
        await self._barber(branch_id, barber_id)
        await self._validate_exception(barber_id, data)
        row = BarberScheduleException(
            barber_id=barber_id,
            date_from=data.date_from,
            date_to=data.date_to,
            kind=data.kind,
            intervals=_intervals_json(data.intervals),
            note=data.note,
        )
        self.repo.add(row)
        await self.session.flush()
        self.audit.record(
            actor, "schedule_exception.create", "barber", barber_id, after=snapshot(row)
        )
        await self.session.commit()
        await self.cache.bump([barber_id])
        return ScheduleChange(row, await self._conflicts(branch_id, barber_id, now))

    async def _get_exception(
        self, branch_id: uuid.UUID, barber_id: uuid.UUID, exception_id: uuid.UUID
    ) -> BarberScheduleException:
        await self._barber(branch_id, barber_id)
        row = await self.repo.get_exception(barber_id, exception_id)
        if row is None:
            raise NotFoundError("Schedule exception not found")
        return row

    async def update_exception(
        self,
        branch_id: uuid.UUID,
        barber_id: uuid.UUID,
        exception_id: uuid.UUID,
        data: ScheduleExceptionIn,
        actor: Actor,
        now: datetime,
    ) -> ScheduleChange[BarberScheduleException]:
        row = await self._get_exception(branch_id, barber_id, exception_id)
        await self._validate_exception(barber_id, data, exclude_id=row.id)
        before = snapshot(row)
        row.date_from = data.date_from
        row.date_to = data.date_to
        row.kind = data.kind
        row.intervals = _intervals_json(data.intervals)
        row.note = data.note
        await self.session.flush()
        self.audit.record(
            actor,
            "schedule_exception.update",
            "barber",
            barber_id,
            before=before,
            after=snapshot(row),
        )
        await self.session.commit()
        await self.cache.bump([barber_id])
        return ScheduleChange(row, await self._conflicts(branch_id, barber_id, now))

    async def delete_exception(
        self,
        branch_id: uuid.UUID,
        barber_id: uuid.UUID,
        exception_id: uuid.UUID,
        actor: Actor,
    ) -> None:
        row = await self._get_exception(branch_id, barber_id, exception_id)
        self.audit.record(
            actor, "schedule_exception.delete", "barber", barber_id, before=snapshot(row)
        )
        await self.repo.delete(row)
        await self.session.commit()
        await self.cache.bump([barber_id])
