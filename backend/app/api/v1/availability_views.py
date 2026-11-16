"""Response builders shared by Mini App and admin availability endpoints."""

from __future__ import annotations

from datetime import date

from app.schemas.schedule import AvailabilityDay, AvailabilityDaysOut, AvailabilitySlotsOut, Slot
from app.services.availability import AvailabilityResult


def days_out(result: AvailabilityResult, working: set[date] | None = None) -> AvailabilityDaysOut:
    return AvailabilityDaysOut(
        timezone=result.timezone,
        days=[
            AvailabilityDay(
                date=day.day,
                slots_count=len(day.slots),
                working=True if working is None else day.day in working,
            )
            for day in result.days
        ],
    )


def slots_out(result: AvailabilityResult, requested_date: date) -> AvailabilitySlotsOut:
    day = result.days[0] if result.days else None
    return AvailabilitySlotsOut(
        date=day.day if day else requested_date,
        timezone=result.timezone,
        step_min=result.step_min,
        durations=result.durations,
        slots=[
            Slot(start_at=start, barber_ids=barber_ids)
            for start, barber_ids in (day.sorted_items() if day else [])
        ],
    )
