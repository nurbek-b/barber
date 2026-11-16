"""Free slots for the Mini App and the admin panel.

Data access is constant in the number of barbers and days: one query each for barbers that
perform the services, their service links, weekly templates, exceptions and busy intervals.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationAppError
from app.domain.slots import (
    BarberInput,
    DaySlots,
    Interval,
    SlotRules,
    bookable_dates,
    compute_slots,
    local_day_bounds,
    working_intervals,
)
from app.models import Barber, BarberSchedule, BarberScheduleException, SalonSettings
from app.repositories.catalog import BarberRepository, BarberServiceRepository
from app.repositories.schedule import BookingReadRepository, ScheduleRepository
from app.services.branches import BranchService
from app.services.catalog import effective_duration
from app.services.schedule import to_domain_schedule
from app.services.slot_cache import CacheKey, SlotCache

MAX_RANGE_DAYS = 62
MAX_SERVICES = 10
# "now" for cached computations: lead time and past filtering are applied after the cache.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class Audience(StrEnum):
    CLIENT = "client"  # Mini App: online-bookable barbers, lead time, horizon
    STAFF = "staff"  # admin panel: any active barber, no lead time / horizon


@dataclass(frozen=True, slots=True)
class AvailabilityResult:
    timezone: str
    step_min: int
    durations: dict[uuid.UUID, int]
    days: list[DaySlots]


class AvailabilityService:
    def __init__(self, session: AsyncSession, cache: SlotCache) -> None:
        self.session = session
        self.cache = cache
        self.branches = BranchService(session)
        self.barbers = BarberRepository(session)
        self.links = BarberServiceRepository(session)
        self.schedules = ScheduleRepository(session)
        self.bookings = BookingReadRepository(session)

    async def _candidates(
        self,
        branch_id: uuid.UUID,
        service_ids: Sequence[uuid.UUID],
        barber_id: uuid.UUID | None,
        audience: Audience,
    ) -> list[Barber]:
        only_bookable = audience is Audience.CLIENT
        if barber_id is not None:
            barber = await self.barbers.get(branch_id, barber_id)
            if barber is None or not barber.is_active:
                raise NotFoundError("Barber not found")
            if only_bookable and not barber.is_bookable_online:
                raise NotFoundError("Barber not found")
            return [barber]
        barbers, _ = await self.barbers.list_page(
            branch_id, only_active=True, only_bookable=only_bookable, limit=1000
        )
        return barbers

    async def _durations(
        self, barbers: Sequence[Barber], service_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        """Total duration per barber; barbers lacking any of the services are dropped."""
        wanted = set(service_ids)
        totals: dict[uuid.UUID, int] = defaultdict(int)
        covered: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
        pairs = await self.links.list_with_services([b.id for b in barbers], only_active=True)
        for link, service in pairs:
            if service.id in wanted:
                totals[link.barber_id] += effective_duration(link, service)
                covered[link.barber_id].add(service.id)
        return {b.id: totals[b.id] for b in barbers if covered[b.id] == wanted}

    def _rules(self, salon: SalonSettings, audience: Audience) -> SlotRules:
        if audience is Audience.STAFF:
            return SlotRules(step_min=salon.slot_step_min, buffer_min=salon.buffer_min)
        return SlotRules(
            step_min=salon.slot_step_min,
            buffer_min=salon.buffer_min,
            min_lead_time_min=salon.min_lead_time_min,
            max_days_ahead=salon.max_days_ahead,
        )

    async def compute(
        self,
        branch_id: uuid.UUID,
        *,
        service_ids: Sequence[uuid.UUID],
        barber_id: uuid.UUID | None,
        date_from: date,
        date_to: date,
        now: datetime,
        audience: Audience,
        extra_busy: Mapping[uuid.UUID, Sequence[Interval]] | None = None,
        exclude_booking_ids: Sequence[uuid.UUID] = (),
    ) -> AvailabilityResult:
        """`extra_busy`: intervals not stored in the DB (Redis holds of other clients).
        `exclude_booking_ids`: treat these bookings as free (moving a booking); bypasses cache."""
        unique_services = list(dict.fromkeys(service_ids))
        if not unique_services:
            raise ValidationAppError("Select at least one service", code="services_required")
        if len(unique_services) > MAX_SERVICES:
            raise ValidationAppError("Too many services", code="too_many_services")
        if date_to < date_from or (date_to - date_from).days >= MAX_RANGE_DAYS:
            raise ValidationAppError(
                f"Date range must be 1..{MAX_RANGE_DAYS} days", code="invalid_date_range"
            )

        salon = await self.branches.settings(branch_id)
        tz = ZoneInfo(salon.timezone)
        rules = self._rules(salon, audience)
        days = bookable_dates(date_from, date_to, rules, now, tz)

        barbers = await self._candidates(branch_id, unique_services, barber_id, audience)
        durations = await self._durations(barbers, unique_services)
        if barber_id is not None and barber_id not in durations:
            raise ValidationAppError(
                "The barber does not perform all selected services", code="services_not_offered"
            )
        result = AvailabilityResult(salon.timezone, rules.step_min, durations, [])
        if not days or not durations:
            result.days.extend(DaySlots(day) for day in days)
            return result

        raw = await self._raw_slots(salon, tz, rules, days, durations, exclude_booking_ids)
        earliest = now + timedelta(minutes=rules.min_lead_time_min)
        order = [barber.id for barber in barbers if barber.id in durations]
        holds = extra_busy or {}
        for day in days:
            day_slots = DaySlots(day)
            for barber_id_ in order:
                need = timedelta(minutes=durations[barber_id_] + rules.buffer_min)
                held = holds.get(barber_id_, ())
                for start in raw[(barber_id_, day)]:
                    if start < earliest:
                        continue
                    if held and any(Interval(start, start + need).overlaps(h) for h in held):
                        continue
                    day_slots.slots.setdefault(start, []).append(barber_id_)
            result.days.append(day_slots)
        return result

    async def _raw_slots(
        self,
        salon: SalonSettings,
        tz: ZoneInfo,
        rules: SlotRules,
        days: Sequence[date],
        durations: Mapping[uuid.UUID, int],
        exclude_booking_ids: Sequence[uuid.UUID] = (),
    ) -> dict[CacheKey, list[datetime]]:
        """Slots per (barber, day) before lead time and holds; served from cache if possible."""
        fingerprint = f"{rules.step_min}:{rules.buffer_min}:{salon.timezone}"
        keys = [(barber_id, day) for barber_id in durations for day in days]
        excluded = set(exclude_booking_ids)
        cached: dict[CacheKey, list[datetime]] = {}
        versions: dict[uuid.UUID, str] = {}
        if not excluded:
            cached, versions = await self.cache.get_many(keys, durations, fingerprint)
        missing = [key for key in keys if key not in cached]
        if not missing:
            return cached

        barber_ids = sorted({barber_id for barber_id, _ in missing})
        missing_days = sorted({day for _, day in missing})
        first, last = missing_days[0], missing_days[-1]
        weekly = await self.schedules.weekly_for(barber_ids)
        exceptions = await self.schedules.exceptions_for(
            barber_ids, first - timedelta(days=1), last
        )
        busy_rows = await self.bookings.active_between(
            barber_ids,
            local_day_bounds(first, tz).start,
            local_day_bounds(last, tz).end + timedelta(days=1),
        )

        weekly_by: dict[uuid.UUID, list[BarberSchedule]] = defaultdict(list)
        for row in weekly:
            weekly_by[row.barber_id].append(row)
        exceptions_by: dict[uuid.UUID, list[BarberScheduleException]] = defaultdict(list)
        for exc in exceptions:
            exceptions_by[exc.barber_id].append(exc)
        busy_by: dict[uuid.UUID, list[Interval]] = defaultdict(list)
        for busy in busy_rows:
            if busy.booking_id in excluded:
                continue
            busy_by[busy.barber_id].append(Interval(busy.start_at, busy.blocked_until))

        computed: dict[CacheKey, list[datetime]] = {}
        no_lead = SlotRules(step_min=rules.step_min, buffer_min=rules.buffer_min)
        wanted = set(missing)
        for barber_id in barber_ids:
            barber_input = BarberInput(
                barber_id=barber_id,
                schedule=to_domain_schedule(weekly_by[barber_id], exceptions_by[barber_id]),
                duration_min=durations[barber_id],
                busy=tuple(busy_by[barber_id]),
            )
            barber_days = [day for day in missing_days if (barber_id, day) in wanted]
            for day_slots in compute_slots(barber_days, [barber_input], no_lead, _EPOCH, tz):
                computed[(barber_id, day_slots.day)] = sorted(day_slots.slots)

        if not excluded:
            await self.cache.set_many(computed, versions, durations, fingerprint)
        return {**cached, **computed}

    async def working_days(
        self, barber_ids: Sequence[uuid.UUID], days: Sequence[date], tz: ZoneInfo
    ) -> set[date]:
        """Days on which at least one of the barbers works (weekly hours minus exceptions).
        Tells a fully booked day apart from a day off — only the former has a waitlist."""
        if not barber_ids or not days:
            return set()
        repo = ScheduleRepository(self.session)
        weekly = await repo.weekly_for(barber_ids)
        exceptions = await repo.exceptions_for(barber_ids, min(days), max(days))
        schedules = [
            to_domain_schedule(
                [row for row in weekly if row.barber_id == barber_id],
                [row for row in exceptions if row.barber_id == barber_id],
            )
            for barber_id in barber_ids
        ]
        return {
            day
            for day in days
            if any(working_intervals(day, schedule, tz) for schedule in schedules)
        }
