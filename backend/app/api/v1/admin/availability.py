from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import AdminContext, NowDep, SessionDep, SlotCacheDep, ensure_own_barber, require
from app.api.v1.availability_views import slots_out
from app.core.errors import ErrorResponse
from app.schemas.schedule import AvailabilitySlotsOut
from app.services.availability import Audience, AvailabilityService
from app.services.permissions import Perm

router = APIRouter(prefix="/availability", tags=["admin-availability"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

CanRead = Annotated[
    AdminContext, Depends(require(Perm.BOOKINGS_WRITE, Perm.BOOKINGS_READ, Perm.BOOKINGS_READ_OWN))
]


@router.get("/slots", response_model=AvailabilitySlotsOut, responses=ERRORS)
async def admin_availability_slots(
    ctx: CanRead,
    session: SessionDep,
    cache: SlotCacheDep,
    now: NowDep,
    service_ids: Annotated[list[uuid.UUID], Query(min_length=1, max_length=10)],
    day: Annotated[date, Query(alias="date")],
    barber_id: uuid.UUID | None = None,
) -> AvailabilitySlotsOut:
    """Staff view: includes barbers hidden from online booking, ignores the lead time and the
    booking horizon (bookings by phone). Past dates return nothing."""
    if not ctx.can(Perm.BOOKINGS_READ):
        if barber_id is None:
            barber_id = ctx.admin.barber_id
        if barber_id is None:
            return AvailabilitySlotsOut(date=day, timezone="", step_min=0, durations={}, slots=[])
        ensure_own_barber(ctx, barber_id, Perm.BOOKINGS_READ)
    result = await AvailabilityService(session, cache).compute(
        ctx.branch_id,
        service_ids=service_ids,
        barber_id=barber_id,
        date_from=day,
        date_to=day,
        now=now,
        audience=Audience.STAFF,
    )
    return slots_out(result, day)
