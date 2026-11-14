from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    AdminContext,
    NowDep,
    RedisDep,
    SessionDep,
    SlotCacheDep,
    ensure_own_barber,
    require,
)
from app.api.v1.booking_views import admin_bookings_out
from app.core.errors import ErrorResponse, ValidationAppError
from app.domain.slots import local_day_bounds
from app.models import Booking
from app.models.enums import BookingStatus
from app.schemas.bookings import (
    AdminBookingCreateIn,
    AdminBookingOut,
    AdminBookingPage,
    AdminBookingPatch,
    BlockIn,
    MoveIn,
    StatusChangeIn,
)
from app.services.admin_bookings import AdminBookingService
from app.services.branches import BranchService
from app.services.permissions import Perm

router = APIRouter(tags=["admin-bookings"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse, "description": "slot_conflict → details.alternatives"},
    412: {"model": ErrorResponse, "description": "version_mismatch"},
    422: {"model": ErrorResponse},
}

CanRead = Annotated[AdminContext, Depends(require(Perm.BOOKINGS_READ, Perm.BOOKINGS_READ_OWN))]
CanWrite = Annotated[AdminContext, Depends(require(Perm.BOOKINGS_WRITE))]
CanStatus = Annotated[AdminContext, Depends(require(Perm.BOOKINGS_WRITE, Perm.BOOKINGS_STATUS_OWN))]


def _service(session: SessionDep, redis: RedisDep, cache: SlotCacheDep) -> AdminBookingService:
    return AdminBookingService(session, redis, cache)


Service = Annotated[AdminBookingService, Depends(_service)]


def _scope_barbers(ctx: AdminContext, barber_ids: list[uuid.UUID] | None) -> list[uuid.UUID] | None:
    if ctx.can(Perm.BOOKINGS_READ):
        return barber_ids
    return [ctx.admin.barber_id] if ctx.admin.barber_id else []


async def _one(session: SessionDep, booking: Booking) -> AdminBookingOut:
    (item,) = await admin_bookings_out(session, [booking])
    return item


@router.get("/bookings", response_model=AdminBookingPage, responses=ERRORS)
async def list_bookings(
    ctx: CanRead,
    session: SessionDep,
    service: Service,
    date_from: date | None = None,
    date_to: date | None = None,
    barber_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    status_: Annotated[list[BookingStatus] | None, Query(alias="status")] = None,
    client_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminBookingPage:
    """Dates are local salon dates (inclusive)."""
    salon = await BranchService(session).settings(ctx.branch_id)
    tz = ZoneInfo(salon.timezone)
    items, total = await service.search(
        ctx.branch_id,
        date_from=local_day_bounds(date_from, tz).start if date_from else None,
        date_to=local_day_bounds(date_to, tz).end if date_to else None,
        barber_ids=_scope_barbers(ctx, barber_id),
        statuses=status_,
        client_id=client_id,
        include_blocks=False,
        limit=limit,
        offset=offset,
    )
    return AdminBookingPage(
        items=await admin_bookings_out(session, items), total=total, limit=limit, offset=offset
    )


@router.get("/calendar", response_model=list[AdminBookingOut], responses=ERRORS)
async def calendar(
    ctx: CanRead,
    session: SessionDep,
    service: Service,
    date_from: date,
    date_to: date,
    barber_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    include_cancelled: bool = False,
) -> list[AdminBookingOut]:
    """Bookings and blocks for the day/week calendar (columns per barber)."""
    if date_to < date_from or date_to - date_from > timedelta(days=31):
        raise ValidationAppError("Range must be up to 31 days", code="invalid_date_range")
    salon = await BranchService(session).settings(ctx.branch_id)
    tz = ZoneInfo(salon.timezone)
    statuses = (
        None
        if include_cancelled
        else [
            BookingStatus.PENDING,
            BookingStatus.CONFIRMED,
            BookingStatus.COMPLETED,
            BookingStatus.NO_SHOW,
        ]
    )
    items, _ = await service.search(
        ctx.branch_id,
        date_from=local_day_bounds(date_from, tz).start,
        date_to=local_day_bounds(date_to, tz).end,
        barber_ids=_scope_barbers(ctx, barber_id),
        statuses=statuses,
        client_id=None,
        include_blocks=True,
        limit=5000,
        offset=0,
    )
    return await admin_bookings_out(session, items)


@router.post("/bookings", response_model=AdminBookingOut, status_code=201, responses=ERRORS)
async def create_booking(
    body: AdminBookingCreateIn, ctx: CanWrite, session: SessionDep, service: Service, now: NowDep
) -> AdminBookingOut:
    """Booking by phone. Overlaps are always rejected (409); working hours can be ignored."""
    return await _one(session, await service.create(ctx.branch_id, body, ctx.actor, now))


@router.get("/bookings/{booking_id}", response_model=AdminBookingOut, responses=ERRORS)
async def get_booking(
    booking_id: uuid.UUID, ctx: CanRead, session: SessionDep, service: Service
) -> AdminBookingOut:
    booking = await service.get(ctx.branch_id, booking_id)
    ensure_own_barber(ctx, booking.barber_id, Perm.BOOKINGS_READ)
    return await _one(session, booking)


@router.patch("/bookings/{booking_id}", response_model=AdminBookingOut, responses=ERRORS)
async def update_booking(
    booking_id: uuid.UUID,
    body: AdminBookingPatch,
    ctx: CanWrite,
    session: SessionDep,
    service: Service,
    now: NowDep,
) -> AdminBookingOut:
    """Actual services and prices, notes, payment. `version` guards against lost updates."""
    booking = await service.patch(ctx.branch_id, booking_id, body, ctx.actor, now)
    return await _one(session, booking)


@router.post("/bookings/{booking_id}/status", response_model=AdminBookingOut, responses=ERRORS)
async def change_status(
    booking_id: uuid.UUID,
    body: StatusChangeIn,
    ctx: CanStatus,
    session: SessionDep,
    service: Service,
    now: NowDep,
) -> AdminBookingOut:
    """pending → confirmed → completed / cancelled / no_show."""
    booking = await service.change_status(
        ctx.branch_id, booking_id, body, ctx.actor, ctx.role, ctx.admin.barber_id, now
    )
    return await _one(session, booking)


@router.post("/bookings/{booking_id}/move", response_model=AdminBookingOut, responses=ERRORS)
async def move_booking(
    booking_id: uuid.UUID,
    body: MoveIn,
    ctx: CanWrite,
    session: SessionDep,
    service: Service,
    now: NowDep,
) -> AdminBookingOut:
    """Calendar drag-and-drop. 409 if the target time is taken, 412 if edited meanwhile."""
    booking = await service.move(ctx.branch_id, booking_id, body, ctx.actor, now)
    return await _one(session, booking)


@router.post("/blocks", response_model=AdminBookingOut, status_code=201, responses=ERRORS)
async def create_block(
    body: BlockIn, ctx: CanWrite, session: SessionDep, service: Service, now: NowDep
) -> AdminBookingOut:
    """Block a barber's time (lunch, meeting). Shares the overlap constraint with bookings."""
    return await _one(session, await service.create_block(ctx.branch_id, body, ctx.actor, now))


@router.delete("/blocks/{block_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
async def delete_block(block_id: uuid.UUID, ctx: CanWrite, service: Service) -> None:
    await service.delete_block(ctx.branch_id, block_id, ctx.actor)
