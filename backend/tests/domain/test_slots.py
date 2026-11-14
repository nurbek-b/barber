from __future__ import annotations

import time as perf
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.domain.slots import (
    BarberInput,
    BarberSchedule,
    ExceptionKind,
    Interval,
    LocalInterval,
    ScheduleException,
    SlotRules,
    WeeklyInterval,
    align_up,
    bookable_dates,
    bookings_outside_schedule,
    compute_slots,
    find_local_overlap,
    find_weekly_overlap,
    local_day_bounds,
    merge,
    pick_least_loaded,
    working_intervals,
)

BISHKEK = ZoneInfo("Asia/Bishkek")  # UTC+6, no DST
BERLIN = ZoneInfo("Europe/Berlin")  # DST: 2026-03-29 (+1→+2), 2026-10-25 (+2→+1)

MONDAY = date(2026, 12, 7)
TUESDAY = MONDAY + timedelta(days=1)
LONG_AGO = datetime(2026, 1, 1, tzinfo=UTC)  # "now" far in the past: no lead-time effects
RULES = SlotRules(step_min=15)
B1 = uuid.UUID(int=1)
B2 = uuid.UUID(int=2)


def at(day: date, hh: int, mm: int = 0, tz: ZoneInfo = BISHKEK) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=tz).astimezone(UTC)


def week(*intervals: tuple[int, str, str]) -> tuple[WeeklyInterval, ...]:
    return tuple(
        WeeklyInterval(weekday, time.fromisoformat(start), time.fromisoformat(end))
        for weekday, start, end in intervals
    )


def every_day(start: str, end: str) -> tuple[WeeklyInterval, ...]:
    return week(*((weekday, start, end) for weekday in range(7)))


def barber(
    weekly: tuple[WeeklyInterval, ...],
    duration: int = 60,
    busy: tuple[Interval, ...] = (),
    exceptions: tuple[ScheduleException, ...] = (),
    barber_id: uuid.UUID = B1,
) -> BarberInput:
    return BarberInput(
        barber_id=barber_id,
        schedule=BarberSchedule(weekly=weekly, exceptions=exceptions),
        duration_min=duration,
        busy=busy,
    )


def slots(
    day: date,
    *barbers: BarberInput,
    rules: SlotRules = RULES,
    now: datetime = LONG_AGO,
    tz: ZoneInfo = BISHKEK,
) -> list[datetime]:
    (result,) = compute_slots([day], barbers, rules, now, tz)
    return [start for start, _ in result.sorted_items()]


def local_times(items: list[datetime], tz: ZoneInfo = BISHKEK) -> list[str]:
    return [item.astimezone(tz).strftime("%H:%M") for item in items]


# ---------------------------------------------------------------------------
# basic day
# ---------------------------------------------------------------------------


def test_plain_day_grid_and_end_of_day() -> None:
    result = slots(MONDAY, barber(week((0, "10:00", "19:00"))))
    times = local_times(result)
    assert times[0] == "10:00"
    assert times[-1] == "18:00", "last slot must end exactly at closing time"
    assert len(times) == 33  # 10:00 .. 18:00 every 15 min


def test_day_without_schedule_is_empty() -> None:
    assert slots(TUESDAY, barber(week((0, "10:00", "19:00")))) == []


def test_duration_longer_than_shift() -> None:
    assert slots(MONDAY, barber(week((0, "10:00", "11:00")), duration=90)) == []


def test_exact_fit() -> None:
    assert local_times(slots(MONDAY, barber(week((0, "10:00", "11:00")), duration=60))) == ["10:00"]


def test_buffer_is_required_after_the_last_client_too() -> None:
    rules = SlotRules(step_min=15, buffer_min=15)
    times = local_times(slots(MONDAY, barber(week((0, "10:00", "19:00")), 45), rules=rules))
    assert times[-1] == "18:00"  # 18:00 + 45 + 15 = 19:00


def test_shift_start_not_on_grid_is_aligned_up() -> None:
    times = local_times(slots(MONDAY, barber(week((0, "10:10", "12:00")), 30)))
    assert times[0] == "10:15"
    assert times[-1] == "11:30"


def test_step_30() -> None:
    times = local_times(
        slots(MONDAY, barber(week((0, "10:00", "12:00")), 30), rules=SlotRules(step_min=30))
    )
    assert times == ["10:00", "10:30", "11:00", "11:30"]


# ---------------------------------------------------------------------------
# breaks
# ---------------------------------------------------------------------------


def test_break_between_intervals() -> None:
    schedule = week((0, "10:00", "14:00"), (0, "15:00", "19:00"))
    times = local_times(slots(MONDAY, barber(schedule, 45)))
    assert "13:15" in times  # ends 14:00
    assert "13:30" not in times  # would run into the break
    assert "14:00" not in times
    assert "14:45" not in times
    assert "15:00" in times


def test_adjacent_intervals_are_merged() -> None:
    schedule = week((0, "10:00", "12:00"), (0, "12:00", "14:00"))
    assert "11:30" in local_times(slots(MONDAY, barber(schedule, 60)))


# ---------------------------------------------------------------------------
# bookings, buffers, blocks
# ---------------------------------------------------------------------------


def test_booking_blocks_overlapping_starts() -> None:
    busy = (Interval(at(MONDAY, 12), at(MONDAY, 13)),)
    times = local_times(slots(MONDAY, barber(week((0, "10:00", "19:00")), 60, busy)))
    assert "11:00" in times  # ends exactly when booking starts
    assert "11:15" not in times
    assert "12:00" not in times
    assert "12:45" not in times
    assert "13:00" in times  # starts exactly when booking ends


def test_new_slot_respects_buffer_before_next_booking() -> None:
    rules = SlotRules(step_min=15, buffer_min=10)
    busy = (Interval(at(MONDAY, 12), at(MONDAY, 13, 10)),)  # booking incl. its own buffer
    times = local_times(slots(MONDAY, barber(week((0, "10:00", "19:00")), 60, busy), rules=rules))
    assert "10:45" in times  # 10:45 + 60 + 10 = 11:55 <= 12:00
    assert "11:00" not in times  # 11:00 + 70 = 12:10 > 12:00
    assert "13:00" not in times  # previous booking's buffer until 13:10
    assert "13:15" in times


def test_odd_booking_end_jumps_to_next_grid_point() -> None:
    busy = (Interval(at(MONDAY, 10, 0), at(MONDAY, 10, 50)),)
    times = local_times(slots(MONDAY, barber(week((0, "10:00", "12:00")), 30, busy)))
    assert times[0] == "11:00"


def test_overlapping_and_unsorted_busy_intervals() -> None:
    busy = (
        Interval(at(MONDAY, 15), at(MONDAY, 16)),
        Interval(at(MONDAY, 11), at(MONDAY, 12, 30)),
        Interval(at(MONDAY, 12), at(MONDAY, 13)),  # overlaps the previous one
    )
    times = local_times(slots(MONDAY, barber(week((0, "10:00", "17:00")), 60, busy)))
    assert times == ["10:00", "13:00", "13:15", "13:30", "13:45", "14:00", "16:00"]


def test_busy_spanning_whole_day() -> None:
    busy = (Interval(at(MONDAY, 0), at(TUESDAY, 0)),)
    assert slots(MONDAY, barber(week((0, "10:00", "19:00")), 30, busy)) == []


def test_busy_on_other_days_is_ignored() -> None:
    busy = (Interval(at(MONDAY - timedelta(days=7), 10), at(MONDAY - timedelta(days=7), 19)),)
    assert len(slots(MONDAY, barber(week((0, "10:00", "11:00")), 30, busy))) == 3


# ---------------------------------------------------------------------------
# overnight shifts and midnight
# ---------------------------------------------------------------------------


def test_overnight_shift_slots_split_by_local_date() -> None:
    schedule = week((0, "20:00", "02:00"))  # Monday 20:00 -> Tuesday 02:00
    monday = local_times(slots(MONDAY, barber(schedule, 60)))
    tuesday = local_times(slots(TUESDAY, barber(schedule, 60)))
    assert monday[0] == "20:00"
    assert monday[-1] == "23:45", "slot starting 23:45 ends 00:45 — still inside the shift"
    assert tuesday == ["00:00", "00:15", "00:30", "00:45", "01:00"]


def test_day_off_removes_after_midnight_part_of_overnight_shift() -> None:
    schedule = week((0, "20:00", "02:00"), (1, "10:00", "12:00"))
    exceptions = (ScheduleException(MONDAY, MONDAY, ExceptionKind.DAY_OFF),)
    tuesday = local_times(slots(TUESDAY, barber(schedule, 60, exceptions=exceptions)))
    assert tuesday[0] == "10:00"


def test_sunday_overnight_wraps_into_monday() -> None:
    sunday = MONDAY - timedelta(days=1)
    schedule = week((6, "22:00", "01:00"))
    assert local_times(slots(MONDAY, barber(schedule, 30))) == ["00:00", "00:15", "00:30"]
    assert local_times(slots(sunday, barber(schedule, 30)))[-1] == "23:45"


def test_overnight_shift_continues_into_next_day_shift() -> None:
    schedule = week((0, "20:00", "02:00"), (1, "02:00", "06:00"))
    tuesday = local_times(slots(TUESDAY, barber(schedule, 60)))
    assert "01:30" in tuesday  # spans the boundary between the two shifts


def test_full_day_shift() -> None:
    schedule = week((0, "00:00", "00:00"))  # end <= start → 24 hours
    times = local_times(slots(MONDAY, barber(schedule, 60)))
    assert times[0] == "00:00"
    assert times[-1] == "23:00"


# ---------------------------------------------------------------------------
# exceptions
# ---------------------------------------------------------------------------


def test_vacation_range() -> None:
    exceptions = (ScheduleException(MONDAY, MONDAY + timedelta(days=6), ExceptionKind.VACATION),)
    candidate = barber(every_day("10:00", "19:00"), exceptions=exceptions)
    assert slots(MONDAY + timedelta(days=3), candidate) == []
    assert slots(MONDAY + timedelta(days=7), candidate) != []


def test_custom_hours_replace_template() -> None:
    exceptions = (
        ScheduleException(
            MONDAY,
            MONDAY,
            ExceptionKind.CUSTOM_HOURS,
            (LocalInterval(time(12), time(14)), LocalInterval(time(16), time(17))),
        ),
    )
    times = local_times(
        slots(MONDAY, barber(week((0, "10:00", "19:00")), 60, exceptions=exceptions))
    )
    assert times == ["12:00", "12:15", "12:30", "12:45", "13:00", "16:00"]


def test_custom_hours_on_template_day_off() -> None:
    exceptions = (
        ScheduleException(
            TUESDAY, TUESDAY, ExceptionKind.CUSTOM_HOURS, (LocalInterval(time(10), time(11)),)
        ),
    )
    times = local_times(
        slots(TUESDAY, barber(week((0, "10:00", "19:00")), 60, exceptions=exceptions))
    )
    assert times == ["10:00"]


# ---------------------------------------------------------------------------
# DST (Bishkek has none, but the algorithm must be correct for any tz)
# ---------------------------------------------------------------------------


def test_spring_forward_day() -> None:
    day = date(2026, 3, 29)  # Sunday; 02:00 -> 03:00 in Berlin
    schedule = week((6, "01:00", "05:00"))
    result = slots(day, barber(schedule, 60), tz=BERLIN)
    times = local_times(result, BERLIN)
    assert times[0] == "01:00"
    assert not any(t.startswith("02:") for t in times), "02:xx does not exist that day"
    assert times[-1] == "04:00"
    # the shift lasts 3 real hours: 01:00 CET (00:00Z) .. 05:00 CEST (03:00Z)
    assert result[-1] - result[0] == timedelta(hours=2)
    assert len(result) == len(set(result))


def test_fall_back_day() -> None:
    day = date(2026, 10, 25)  # Sunday; 03:00 -> 02:00 in Berlin
    schedule = week((6, "01:00", "05:00"))
    result = slots(day, barber(schedule, 60), tz=BERLIN)
    # 5 real hours: 01:00 CEST (23:00Z) .. 05:00 CET (04:00Z); last start 04:00Z = 05:00 - 1h
    assert result[0] == datetime(2026, 10, 24, 23, 0, tzinfo=UTC)
    assert result[-1] == datetime(2026, 10, 25, 3, 0, tzinfo=UTC)
    assert len(result) == 17  # 4 real hours of starts at 15 min + 1
    times = local_times(result, BERLIN)
    assert times.count("02:00") == 2, "the repeated hour yields two distinct instants"


def test_local_day_bounds_lengths() -> None:
    def hours(day: date) -> float:
        bounds = local_day_bounds(day, BERLIN)
        return (bounds.end - bounds.start).total_seconds() / 3600

    assert hours(date(2026, 3, 29)) == 23
    assert hours(date(2026, 10, 25)) == 25
    assert hours(date(2026, 6, 1)) == 24


def test_overnight_shift_across_dst_change() -> None:
    saturday = date(2026, 3, 28)
    schedule = week((5, "22:00", "04:00"))  # ends Sunday 04:00 CEST
    sunday = local_times(
        slots(saturday + timedelta(days=1), barber(schedule, 60), tz=BERLIN), BERLIN
    )
    assert sunday[-1] == "03:00"
    assert "01:45" in sunday  # 01:45 CET + 1h = 03:45 CEST <= 04:00


# ---------------------------------------------------------------------------
# lead time and horizon
# ---------------------------------------------------------------------------


def test_lead_time_hides_near_slots() -> None:
    now = at(MONDAY, 12, 7)
    rules = SlotRules(step_min=15, min_lead_time_min=60)
    times = local_times(
        slots(MONDAY, barber(week((0, "10:00", "19:00")), 30), rules=rules, now=now)
    )
    assert times[0] == "13:15"  # 12:07 + 60 = 13:07 → aligned up


def test_past_day_is_empty() -> None:
    now = at(TUESDAY, 9)
    assert slots(MONDAY, barber(week((0, "10:00", "19:00"))), now=now) == []


def test_lead_time_crossing_midnight() -> None:
    now = at(MONDAY, 23, 30)
    rules = SlotRules(step_min=15, min_lead_time_min=120)
    schedule = week((1, "00:00", "06:00"))
    assert local_times(slots(TUESDAY, barber(schedule, 30), rules=rules, now=now))[0] == "01:30"


def test_bookable_dates_horizon() -> None:
    now = at(MONDAY, 10)
    rules = SlotRules(step_min=15, max_days_ahead=3)
    days = bookable_dates(
        MONDAY - timedelta(days=2), MONDAY + timedelta(days=10), rules, now, BISHKEK
    )
    assert days == [MONDAY + timedelta(days=offset) for offset in range(4)]


def test_bookable_dates_uses_salon_timezone() -> None:
    # 20:00 UTC on Monday is already Tuesday 02:00 in Bishkek
    now = datetime.combine(MONDAY, time(20), tzinfo=UTC)
    days = bookable_dates(MONDAY, TUESDAY, SlotRules(step_min=15), now, BISHKEK)
    assert days == [TUESDAY]


# ---------------------------------------------------------------------------
# any barber
# ---------------------------------------------------------------------------


def test_any_barber_union() -> None:
    first = barber(week((0, "10:00", "12:00")), 60, barber_id=B1)
    second = barber(
        week((0, "11:00", "13:00")),
        60,
        busy=(Interval(at(MONDAY, 11), at(MONDAY, 12)),),
        barber_id=B2,
    )
    (day,) = compute_slots([MONDAY], [first, second], RULES, LONG_AGO, BISHKEK)
    by_time = {
        start.astimezone(BISHKEK).strftime("%H:%M"): ids for start, ids in day.sorted_items()
    }
    assert by_time["10:00"] == [B1]
    assert by_time["11:00"] == [B1]
    assert "11:15" not in by_time
    assert by_time["12:00"] == [B2]


def test_any_barber_uses_each_barbers_own_duration() -> None:
    fast = barber(week((0, "10:00", "11:00")), 30, barber_id=B1)
    slow = barber(week((0, "10:00", "11:00")), 60, barber_id=B2)
    (day,) = compute_slots([MONDAY], [fast, slow], RULES, LONG_AGO, BISHKEK)
    items = {start.astimezone(BISHKEK).strftime("%H:%M"): ids for start, ids in day.sorted_items()}
    assert items == {"10:00": [B1, B2], "10:15": [B1], "10:30": [B1]}


def test_pick_least_loaded() -> None:
    b3 = uuid.UUID(int=3)
    assert pick_least_loaded([B1, B2], {B1: 120, B2: 60}, {}, {}) == B2
    assert pick_least_loaded([B1, B2], {B1: 60, B2: 60}, {B1: 1, B2: 2}, {}) == B1
    assert pick_least_loaded([B1, b3], {}, {}, {B1: 5, b3: 1}) == b3
    with pytest.raises(ValueError, match="no candidates"):
        pick_least_loaded([], {}, {}, {})


# ---------------------------------------------------------------------------
# helpers & validation
# ---------------------------------------------------------------------------


def test_align_up() -> None:
    assert align_up(at(MONDAY, 10, 0), 15, BISHKEK) == at(MONDAY, 10, 0)
    assert align_up(at(MONDAY, 10, 1), 15, BISHKEK) == at(MONDAY, 10, 15)
    assert align_up(at(MONDAY, 10, 14) + timedelta(seconds=59), 15, BISHKEK) == at(MONDAY, 10, 15)
    assert align_up(at(MONDAY, 23, 50), 15, BISHKEK) == at(TUESDAY, 0, 0)


def test_merge() -> None:
    a = Interval(at(MONDAY, 10), at(MONDAY, 11))
    b = Interval(at(MONDAY, 11), at(MONDAY, 12))
    c = Interval(at(MONDAY, 10, 30), at(MONDAY, 10, 45))
    assert merge([b, c, a]) == [Interval(at(MONDAY, 10), at(MONDAY, 12))]


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Interval(datetime(2026, 1, 1), datetime(2026, 1, 2))


def test_working_intervals_include_previous_overnight() -> None:
    schedule = BarberSchedule(week((0, "22:00", "02:00"), (1, "10:00", "12:00")))
    result = working_intervals(TUESDAY, schedule, BISHKEK)
    assert result == [
        Interval(at(MONDAY, 22), at(TUESDAY, 2)),
        Interval(at(TUESDAY, 10), at(TUESDAY, 12)),
    ]


@pytest.mark.parametrize(
    ("intervals", "overlap"),
    [
        ([(0, "10:00", "14:00"), (0, "15:00", "19:00")], False),
        ([(0, "10:00", "14:00"), (0, "14:00", "19:00")], False),
        ([(0, "10:00", "14:00"), (0, "13:00", "19:00")], True),
        ([(0, "20:00", "02:00"), (1, "01:00", "10:00")], True),
        ([(0, "20:00", "02:00"), (1, "02:00", "10:00")], False),
        ([(6, "22:00", "03:00"), (0, "02:00", "10:00")], True),
        ([(6, "22:00", "03:00"), (0, "03:00", "10:00")], False),
        ([(0, "09:00", "18:00"), (0, "10:00", "11:00"), (0, "12:00", "13:00")], True),
    ],
)
def test_find_weekly_overlap(intervals: list[tuple[int, str, str]], overlap: bool) -> None:
    assert (find_weekly_overlap(week(*intervals)) is not None) is overlap


def test_find_local_overlap() -> None:
    assert not find_local_overlap(
        [LocalInterval(time(10), time(12)), LocalInterval(time(12), time(14))]
    )
    assert find_local_overlap(
        [LocalInterval(time(10), time(12)), LocalInterval(time(11), time(14))]
    )


def test_bookings_outside_schedule() -> None:
    schedule = BarberSchedule(
        week((0, "10:00", "19:00")),
        (
            ScheduleException(
                MONDAY, MONDAY, ExceptionKind.CUSTOM_HOURS, (LocalInterval(time(10), time(14)),)
            ),
        ),
    )
    inside = uuid.uuid4()
    outside = uuid.uuid4()
    bookings = [
        (inside, Interval(at(MONDAY, 12), at(MONDAY, 13))),
        (outside, Interval(at(MONDAY, 15), at(MONDAY, 16))),
    ]
    assert bookings_outside_schedule(bookings, schedule, BISHKEK) == [outside]


# ---------------------------------------------------------------------------
# performance: linear scan
# ---------------------------------------------------------------------------


def test_many_bookings_month_is_fast() -> None:
    first_day = MONDAY
    days = [first_day + timedelta(days=offset) for offset in range(31)]
    busy = tuple(
        Interval(at(day, hour, 30), at(day, hour + 1)) for day in days for hour in range(10, 20)
    )
    barbers = [
        barber(every_day("09:00", "21:00"), 30, busy, barber_id=uuid.UUID(int=index))
        for index in range(10)
    ]
    started = perf.perf_counter()
    result = compute_slots(days, barbers, SlotRules(step_min=5), LONG_AGO, BISHKEK)
    elapsed = perf.perf_counter() - started
    assert sum(len(day.slots) for day in result) > 0
    assert elapsed < 1.0, f"took {elapsed:.3f}s"
