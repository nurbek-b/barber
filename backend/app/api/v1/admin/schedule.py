from __future__ import annotations

import uuid
from datetime import date, time
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    AdminContext,
    NowDep,
    SessionDep,
    SlotCacheDep,
    ensure_own_barber,
    require,
)
from app.core.errors import ErrorResponse, ValidationAppError
from app.models import BarberSchedule, BarberScheduleException
from app.repositories.schedule import BusyRow
from app.schemas.schedule import (
    BookingRef,
    LocalIntervalIn,
    ScheduleExceptionIn,
    ScheduleExceptionOut,
    ScheduleExceptionUpdateOut,
    WeeklyIntervalOut,
    WeeklyScheduleOut,
    WeeklySchedulePut,
    WeeklyScheduleUpdateOut,
)
from app.services.permissions import Perm
from app.services.schedule import ScheduleService

router = APIRouter(prefix="/barbers/{barber_id}", tags=["admin-schedule"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

CanRead = Annotated[AdminContext, Depends(require(Perm.BARBERS_READ, Perm.BARBERS_READ_OWN))]
CanWrite = Annotated[AdminContext, Depends(require(Perm.BARBERS_WRITE))]


def _weekly_out(rows: list[BarberSchedule]) -> list[WeeklyIntervalOut]:
    return [WeeklyIntervalOut.model_validate(row) for row in rows]


def _exception_out(row: BarberScheduleException) -> ScheduleExceptionOut:
    return ScheduleExceptionOut(
        id=row.id,
        date_from=row.date_from,
        date_to=row.date_to,
        kind=row.kind,
        intervals=[
            LocalIntervalIn(
                start=time.fromisoformat(item["start"]), end=time.fromisoformat(item["end"])
            )
            for item in row.intervals
        ],
        note=row.note,
    )


def _refs(rows: list[BusyRow]) -> list[BookingRef]:
    return [BookingRef(id=row.booking_id, start_at=row.start_at, end_at=row.end_at) for row in rows]


@router.get("/schedule", response_model=WeeklyScheduleOut, responses=ERRORS)
async def get_schedule(
    barber_id: uuid.UUID, ctx: CanRead, session: SessionDep, cache: SlotCacheDep
) -> WeeklyScheduleOut:
    ensure_own_barber(ctx, barber_id, Perm.BARBERS_READ)
    rows = await ScheduleService(session, cache).weekly(ctx.branch_id, barber_id)
    return WeeklyScheduleOut(intervals=_weekly_out(rows))


@router.put("/schedule", response_model=WeeklyScheduleUpdateOut, responses=ERRORS)
async def replace_schedule(
    barber_id: uuid.UUID,
    body: WeeklySchedulePut,
    ctx: CanWrite,
    session: SessionDep,
    cache: SlotCacheDep,
    now: NowDep,
) -> WeeklyScheduleUpdateOut:
    """Replaces the whole weekly template. Breaks are gaps between intervals of a day."""
    change = await ScheduleService(session, cache).replace_weekly(
        ctx.branch_id, barber_id, body.intervals, ctx.actor, now
    )
    return WeeklyScheduleUpdateOut(
        intervals=_weekly_out(change.value), conflicting_bookings=_refs(change.conflicting)
    )


@router.get("/exceptions", response_model=list[ScheduleExceptionOut], responses=ERRORS)
async def list_exceptions(
    barber_id: uuid.UUID,
    ctx: CanRead,
    session: SessionDep,
    cache: SlotCacheDep,
    date_from: Annotated[date, Query()],
    date_to: Annotated[date, Query()],
) -> list[ScheduleExceptionOut]:
    ensure_own_barber(ctx, barber_id, Perm.BARBERS_READ)
    if date_to < date_from or (date_to - date_from).days > 731:
        raise ValidationAppError("Invalid date range", code="invalid_date_range")
    rows = await ScheduleService(session, cache).list_exceptions(
        ctx.branch_id, barber_id, date_from, date_to
    )
    return [_exception_out(row) for row in rows]


@router.post(
    "/exceptions",
    response_model=ScheduleExceptionUpdateOut,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
async def create_exception(
    barber_id: uuid.UUID,
    body: ScheduleExceptionIn,
    ctx: CanWrite,
    session: SessionDep,
    cache: SlotCacheDep,
    now: NowDep,
) -> ScheduleExceptionUpdateOut:
    change = await ScheduleService(session, cache).create_exception(
        ctx.branch_id, barber_id, body, ctx.actor, now
    )
    return ScheduleExceptionUpdateOut(
        exception=_exception_out(change.value), conflicting_bookings=_refs(change.conflicting)
    )


@router.put(
    "/exceptions/{exception_id}", response_model=ScheduleExceptionUpdateOut, responses=ERRORS
)
async def update_exception(
    barber_id: uuid.UUID,
    exception_id: uuid.UUID,
    body: ScheduleExceptionIn,
    ctx: CanWrite,
    session: SessionDep,
    cache: SlotCacheDep,
    now: NowDep,
) -> ScheduleExceptionUpdateOut:
    change = await ScheduleService(session, cache).update_exception(
        ctx.branch_id, barber_id, exception_id, body, ctx.actor, now
    )
    return ScheduleExceptionUpdateOut(
        exception=_exception_out(change.value), conflicting_bookings=_refs(change.conflicting)
    )


@router.delete(
    "/exceptions/{exception_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS
)
async def delete_exception(
    barber_id: uuid.UUID,
    exception_id: uuid.UUID,
    ctx: CanWrite,
    session: SessionDep,
    cache: SlotCacheDep,
) -> None:
    await ScheduleService(session, cache).delete_exception(
        ctx.branch_id, barber_id, exception_id, ctx.actor
    )
