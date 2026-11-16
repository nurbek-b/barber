from __future__ import annotations

import uuid
from datetime import date, datetime, time

from pydantic import Field, field_validator, model_validator

from app.models.enums import ScheduleExceptionKind
from app.schemas.common import ApiModel

MAX_EXCEPTION_DAYS = 366


def _no_seconds(value: time) -> time:
    if value.second or value.microsecond or value.tzinfo is not None:
        raise ValueError("time must be HH:MM, local to the salon, without seconds or timezone")
    return value


class WeeklyIntervalIn(ApiModel):
    weekday: int = Field(ge=0, le=6, description="0 = Monday … 6 = Sunday")
    start_time: time = Field(examples=["10:00"])
    end_time: time = Field(
        examples=["19:00"], description="end <= start means the shift ends the next day"
    )

    _check_start = field_validator("start_time")(_no_seconds)
    _check_end = field_validator("end_time")(_no_seconds)

    @model_validator(mode="after")
    def _non_empty(self) -> WeeklyIntervalIn:
        if self.start_time == self.end_time:
            raise ValueError("start and end are equal")
        return self


class WeeklyIntervalOut(ApiModel):
    weekday: int
    start_time: time
    end_time: time


class WeeklySchedulePut(ApiModel):
    intervals: list[WeeklyIntervalIn] = Field(max_length=70)


class LocalIntervalIn(ApiModel):
    start: time
    end: time

    _check_start = field_validator("start")(_no_seconds)
    _check_end = field_validator("end")(_no_seconds)

    @model_validator(mode="after")
    def _non_empty(self) -> LocalIntervalIn:
        if self.start == self.end:
            raise ValueError("start and end are equal")
        return self


class ScheduleExceptionIn(ApiModel):
    date_from: date
    date_to: date
    kind: ScheduleExceptionKind
    intervals: list[LocalIntervalIn] = Field(default_factory=list, max_length=10)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _consistent(self) -> ScheduleExceptionIn:
        if self.date_to < self.date_from:
            raise ValueError("date_to is before date_from")
        if (self.date_to - self.date_from).days >= MAX_EXCEPTION_DAYS:
            raise ValueError(f"an exception can span at most {MAX_EXCEPTION_DAYS} days")
        if self.kind is ScheduleExceptionKind.CUSTOM_HOURS and not self.intervals:
            raise ValueError("custom_hours requires at least one interval")
        if self.kind is not ScheduleExceptionKind.CUSTOM_HOURS and self.intervals:
            raise ValueError("intervals are allowed only for custom_hours")
        return self


class ScheduleExceptionOut(ApiModel):
    id: uuid.UUID
    date_from: date
    date_to: date
    kind: ScheduleExceptionKind
    intervals: list[LocalIntervalIn]
    note: str | None


class BookingRef(ApiModel):
    id: uuid.UUID
    start_at: datetime
    end_at: datetime


class WeeklyScheduleOut(ApiModel):
    intervals: list[WeeklyIntervalOut]


class WeeklyScheduleUpdateOut(WeeklyScheduleOut):
    conflicting_bookings: list[BookingRef] = Field(
        description="Upcoming bookings that no longer fit working hours (not cancelled)"
    )


class ScheduleExceptionUpdateOut(ApiModel):
    exception: ScheduleExceptionOut
    conflicting_bookings: list[BookingRef]


# ---------------- availability ----------------


class AvailabilityDay(ApiModel):
    date: date
    slots_count: int
    working: bool = Field(
        default=True, description="false: day off; true with 0 slots: fully booked (waitlist)"
    )


class AvailabilityDaysOut(ApiModel):
    timezone: str
    days: list[AvailabilityDay]


class Slot(ApiModel):
    start_at: datetime = Field(description="UTC")
    barber_ids: list[uuid.UUID] = Field(description="Barbers free at this time")


class AvailabilitySlotsOut(ApiModel):
    date: date
    timezone: str
    step_min: int
    durations: dict[uuid.UUID, int] = Field(
        description="Total duration of the selected services per barber, minutes"
    )
    slots: list[Slot]
