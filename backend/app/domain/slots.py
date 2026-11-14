"""Free-slot computation. Pure functions, no IO: everything is passed in, results are returned.

Conventions
-----------
* All instants are timezone-aware UTC ``datetime``; local wall-clock values (``date``, ``time``)
  are interpreted in the salon timezone and converted here, per date, so DST is handled.
* A slot belongs to the *local date of its start*.
* A weekly interval with ``end <= start`` ends on the next day (overnight shift). The part
  after midnight still belongs to the shift of the previous date: a day off on Monday also
  removes the early hours of Tuesday that Monday's overnight shift would cover.
* Breaks are gaps between the working intervals of a day.
* A slot ``t`` is available iff ``[t, t + duration + buffer)`` lies inside one working interval
  and does not intersect any busy interval (active bookings use ``[start_at, blocked_until)``,
  i.e. their own buffer is already included; blocks and holds are busy intervals too).

Complexity: for one barber and one day the scan is a single pass over the sorted working and
busy intervals — O(S + B), where S is the number of grid points and B the number of busy
intervals. Busy intervals are sorted once (O(B log B)) per barber for the whole date range.
"""

from __future__ import annotations

import bisect
import itertools
import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

MINUTES_PER_DAY = 24 * 60
MINUTES_PER_WEEK = 7 * MINUTES_PER_DAY


@dataclass(frozen=True, slots=True, order=True)
class Interval:
    """Half-open interval [start, end) of UTC instants."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("Interval bounds must be timezone-aware")
        if self.end < self.start:
            raise ValueError("Interval end is before start")

    def overlaps(self, other: Interval) -> bool:
        return self.start < other.end and other.start < self.end

    def contains(self, other: Interval) -> bool:
        return self.start <= other.start and other.end <= self.end


@dataclass(frozen=True, slots=True)
class LocalInterval:
    """Wall-clock interval of a day; end <= start means it ends on the next day."""

    start: time
    end: time

    @property
    def overnight(self) -> bool:
        return self.end <= self.start


@dataclass(frozen=True, slots=True)
class WeeklyInterval:
    weekday: int  # 0 = Monday ... 6 = Sunday
    start: time
    end: time

    @property
    def local(self) -> LocalInterval:
        return LocalInterval(self.start, self.end)


class ExceptionKind(StrEnum):
    DAY_OFF = "day_off"
    VACATION = "vacation"
    CUSTOM_HOURS = "custom_hours"


@dataclass(frozen=True, slots=True)
class ScheduleException:
    date_from: date
    date_to: date  # inclusive
    kind: ExceptionKind
    intervals: tuple[LocalInterval, ...] = ()

    def covers(self, day: date) -> bool:
        return self.date_from <= day <= self.date_to


@dataclass(frozen=True, slots=True)
class BarberSchedule:
    weekly: tuple[WeeklyInterval, ...]
    exceptions: tuple[ScheduleException, ...] = ()


@dataclass(frozen=True, slots=True)
class SlotRules:
    step_min: int
    buffer_min: int = 0
    min_lead_time_min: int = 0
    max_days_ahead: int | None = None  # None: no horizon (admin)

    def __post_init__(self) -> None:
        if self.step_min <= 0 or self.buffer_min < 0 or self.min_lead_time_min < 0:
            raise ValueError("invalid slot rules")


# ---------------------------------------------------------------------------
# local time -> UTC
# ---------------------------------------------------------------------------


def to_utc(day: date, wall: time, tz: ZoneInfo) -> datetime:
    """Local wall-clock -> UTC. Non-existent times (DST gap) resolve with the pre-transition
    offset (fold=0), so a shift 01:00–05:00 on a spring-forward day lasts 3 real hours."""
    return datetime.combine(day, wall, tzinfo=tz).astimezone(UTC)


def local_day_bounds(day: date, tz: ZoneInfo) -> Interval:
    """[local midnight of `day`, local midnight of the next day) in UTC (23/24/25 hours)."""
    return Interval(to_utc(day, time(0), tz), to_utc(day + timedelta(days=1), time(0), tz))


def _shift_to_utc(day: date, interval: LocalInterval, tz: ZoneInfo) -> Interval:
    end_day = day + timedelta(days=1) if interval.overnight else day
    return Interval(to_utc(day, interval.start, tz), to_utc(end_day, interval.end, tz))


def shifts_of_date(day: date, schedule: BarberSchedule) -> tuple[LocalInterval, ...]:
    """Working intervals that *start* on `day` after applying exceptions."""
    for exception in schedule.exceptions:
        if exception.covers(day):
            if exception.kind is ExceptionKind.CUSTOM_HOURS:
                return exception.intervals
            return ()
    weekday = day.weekday()
    return tuple(item.local for item in schedule.weekly if item.weekday == weekday)


def merge(intervals: Iterable[Interval]) -> list[Interval]:
    """Sort and merge overlapping or touching intervals."""
    result: list[Interval] = []
    for current in sorted(intervals):
        if current.end <= current.start:
            continue
        if result and current.start <= result[-1].end:
            if current.end > result[-1].end:
                result[-1] = Interval(result[-1].start, current.end)
        else:
            result.append(current)
    return result


def working_intervals(day: date, schedule: BarberSchedule, tz: ZoneInfo) -> list[Interval]:
    """UTC working intervals relevant to slots starting on local `day`: shifts of `day` plus the
    after-midnight part of the previous day's overnight shifts. Not clipped to the day: a slot
    starting at 23:30 may legitimately end after midnight."""
    previous = day - timedelta(days=1)
    bounds = local_day_bounds(day, tz)
    candidates = [_shift_to_utc(day, item, tz) for item in shifts_of_date(day, schedule)]
    candidates += [
        _shift_to_utc(previous, item, tz)
        for item in shifts_of_date(previous, schedule)
        if item.overnight
    ]
    return [item for item in merge(candidates) if item.end > bounds.start]


# ---------------------------------------------------------------------------
# grid
# ---------------------------------------------------------------------------


def align_up(instant: datetime, step_min: int, tz: ZoneInfo) -> datetime:
    """Smallest instant >= `instant` whose local wall-clock minute-of-day is a multiple of step
    (10:00, 10:15, ...). Offsets of real timezones are multiples of 15/30 minutes, so stepping
    in UTC afterwards keeps the local alignment, including across DST changes."""
    local = instant.astimezone(tz)
    seconds = local.hour * 3600 + local.minute * 60 + local.second
    step_seconds = step_min * 60
    remainder = seconds % step_seconds
    if remainder == 0 and local.microsecond == 0:
        return instant
    delta = timedelta(seconds=step_seconds - remainder, microseconds=-local.microsecond)
    return instant + delta


def scan_free_starts(
    work: Sequence[Interval],
    busy: Sequence[Interval],
    *,
    need: timedelta,
    step_min: int,
    window: Interval,
    tz: ZoneInfo,
    busy_ends: Sequence[datetime] | None = None,
) -> list[datetime]:
    """Single pass over sorted `work` and merged, sorted `busy`.

    Returns aligned starts t in `window` with [t, t+need) ⊆ some work interval and disjoint
    from all busy intervals. When t collides with a busy interval the scan jumps straight to
    the first aligned point after it, so it never visits more grid points than exist.
    """
    step = timedelta(minutes=step_min)
    result: list[datetime] = []
    # Busy intervals ending before the window cannot matter: binary-search the first relevant
    # one (`busy_ends` is precomputed once per barber when scanning many days).
    ends = busy_ends if busy_ends is not None else [item.end for item in busy]
    j = bisect.bisect_right(ends, window.start)
    for interval in work:
        if interval.end <= window.start:
            continue
        if interval.start >= window.end:
            break
        t = align_up(max(interval.start, window.start), step_min, tz)
        while t < window.end and t + need <= interval.end:
            while j < len(busy) and busy[j].end <= t:
                j += 1
            if j < len(busy) and busy[j].start < t + need:
                t = align_up(busy[j].end, step_min, tz)
                continue
            result.append(t)
            t += step
    return result


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BarberInput:
    """Everything needed to compute one barber's slots for a date range."""

    barber_id: uuid.UUID
    schedule: BarberSchedule
    duration_min: int  # total of the selected services for this barber
    busy: tuple[Interval, ...] = ()
    sort_order: int = 0


def bookable_dates(
    first: date, last: date, rules: SlotRules, now: datetime, tz: ZoneInfo
) -> list[date]:
    """Dates in [first, last] that are neither in the past nor beyond the horizon."""
    today = now.astimezone(tz).date()
    start = max(first, today)
    end = last
    if rules.max_days_ahead is not None:
        end = min(end, today + timedelta(days=rules.max_days_ahead))
    days = (end - start).days
    return [start + timedelta(days=offset) for offset in range(days + 1)] if days >= 0 else []


def barber_day_slots(
    day: date,
    barber: BarberInput,
    busy_sorted: Sequence[Interval],
    rules: SlotRules,
    now: datetime,
    tz: ZoneInfo,
    busy_ends: Sequence[datetime] | None = None,
) -> list[datetime]:
    bounds = local_day_bounds(day, tz)
    earliest = now + timedelta(minutes=rules.min_lead_time_min)
    if earliest >= bounds.end:
        return []
    window = Interval(max(bounds.start, earliest), bounds.end)
    need = timedelta(minutes=barber.duration_min + rules.buffer_min)
    work = working_intervals(day, barber.schedule, tz)
    return scan_free_starts(
        work,
        busy_sorted,
        need=need,
        step_min=rules.step_min,
        window=window,
        tz=tz,
        busy_ends=busy_ends,
    )


@dataclass(slots=True)
class DaySlots:
    day: date
    # start (UTC) -> barbers free at that start, in barber input order
    slots: dict[datetime, list[uuid.UUID]] = field(default_factory=dict)

    def sorted_items(self) -> list[tuple[datetime, list[uuid.UUID]]]:
        return sorted(self.slots.items())


def compute_slots(
    days: Sequence[date],
    barbers: Sequence[BarberInput],
    rules: SlotRules,
    now: datetime,
    tz: ZoneInfo,
) -> list[DaySlots]:
    """Slots for each date; with several barbers the result is their union ("any barber")."""
    prepared = []
    for barber in barbers:
        busy = merge(barber.busy)
        prepared.append((barber, busy, [item.end for item in busy]))
    result: list[DaySlots] = []
    for day in days:
        day_slots = DaySlots(day)
        for barber, busy, ends in prepared:
            for start in barber_day_slots(day, barber, busy, rules, now, tz, ends):
                day_slots.slots.setdefault(start, []).append(barber.barber_id)
        result.append(day_slots)
    return result


def pick_least_loaded(
    candidates: Sequence[uuid.UUID],
    booked_minutes: Mapping[uuid.UUID, int],
    booking_counts: Mapping[uuid.UUID, int],
    sort_order: Mapping[uuid.UUID, int],
) -> uuid.UUID:
    """'Any barber' assignment: fewest booked minutes that day, then fewer bookings, then
    the salon's sort order, then id (deterministic)."""
    if not candidates:
        raise ValueError("no candidates")
    return min(
        candidates,
        key=lambda barber_id: (
            booked_minutes.get(barber_id, 0),
            booking_counts.get(barber_id, 0),
            sort_order.get(barber_id, 0),
            str(barber_id),
        ),
    )


# ---------------------------------------------------------------------------
# schedule validation and conflicts
# ---------------------------------------------------------------------------


def _minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _week_ranges(item: WeeklyInterval) -> Iterator[tuple[int, int]]:
    start = item.weekday * MINUTES_PER_DAY + _minutes(item.start)
    length = _minutes(item.end) - _minutes(item.start)
    if length <= 0:
        length += MINUTES_PER_DAY
    end = start + length
    if end <= MINUTES_PER_WEEK:
        yield start, end
    else:  # Sunday overnight wraps into Monday
        yield start, MINUTES_PER_WEEK
        yield 0, end - MINUTES_PER_WEEK


def find_weekly_overlap(
    items: Sequence[WeeklyInterval],
) -> tuple[WeeklyInterval, WeeklyInterval] | None:
    """Return the first pair of overlapping intervals (overnight spills included), or None."""
    ranges = sorted(
        (start, end, index) for index, item in enumerate(items) for start, end in _week_ranges(item)
    )
    for (_, prev_end, prev_index), (start, _, index) in itertools.pairwise(ranges):
        if start < prev_end and prev_index != index:
            return items[prev_index], items[index]
    return None


def find_local_overlap(items: Sequence[LocalInterval]) -> bool:
    """Overlap check for one day's intervals (custom hours)."""
    ranges = []
    for item in items:
        start = _minutes(item.start)
        end = _minutes(item.end) + (MINUTES_PER_DAY if item.overnight else 0)
        ranges.append((start, end))
    ranges.sort()
    return any(nxt[0] < cur[1] for cur, nxt in itertools.pairwise(ranges))


def bookings_outside_schedule(
    bookings: Sequence[tuple[uuid.UUID, Interval]],
    schedule: BarberSchedule,
    tz: ZoneInfo,
) -> list[uuid.UUID]:
    """Bookings that no longer fit into working hours (e.g. after adding a vacation)."""
    result: list[uuid.UUID] = []
    cache: dict[date, list[Interval]] = {}
    for booking_id, span in bookings:
        day = span.start.astimezone(tz).date()
        work = cache.get(day)
        if work is None:
            work = working_intervals(day, schedule, tz)
            cache[day] = work
        if not any(interval.contains(span) for interval in work):
            result.append(booking_id)
    return result
