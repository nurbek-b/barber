from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Header, Query, Response, status

from app.api.deps import MiniappContext, MiniappDep, NowDep, RedisDep, SessionDep, SlotCacheDep
from app.api.v1.booking_views import client_bookings_out, quote_out
from app.api.v1.miniapp.catalog import to_public_barber
from app.core.errors import ErrorResponse
from app.models import Booking
from app.repositories.catalog import BarberRepository, BarberServiceRepository
from app.schemas.bookings import (
    BookingCreateIn,
    BookingOut,
    BookingPage,
    CancelIn,
    HoldIn,
    HoldOut,
    RepeatDraftOut,
    RescheduleIn,
)
from app.services.bookings import ClientBookingService
from app.services.branches import BranchService

router = APIRouter(tags=["miniapp-bookings"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse, "description": "slot_conflict → details.alternatives"},
    422: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


async def _one(
    ctx: MiniappContext, session: SessionDep, booking: Booking, now: NowDep
) -> BookingOut:
    salon = await BranchService(session).settings(ctx.branch_id)
    (item,) = await client_bookings_out(session, [booking], salon, now)
    return item


@router.post("/holds", response_model=HoldOut, status_code=201, responses=ERRORS)
async def create_hold(
    body: HoldIn,
    ctx: MiniappDep,
    session: SessionDep,
    redis: RedisDep,
    cache: SlotCacheDep,
    now: NowDep,
) -> HoldOut:
    """Reserve a slot for 5 minutes while the client confirms. For 'any barber' the barber
    is assigned here (least loaded that day), so the confirmation screen shows exact prices."""
    placed = await ClientBookingService(session, redis, cache).place_hold(
        ctx.branch_id,
        ctx.identity.client,
        barber_id=body.barber_id,
        service_ids=body.service_ids,
        start_at=body.start_at,
        now=now,
        reschedule_booking_id=body.reschedule_booking_id,
    )
    return HoldOut(
        hold_id=placed.hold.id,
        expires_at=placed.hold.expires_at,
        barber=to_public_barber(placed.barber),
        start_at=placed.hold.start_at,
        end_at=placed.hold.end_at,
        quote=quote_out(placed.quote),
    )


@router.delete("/holds/{hold_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
async def release_hold(
    hold_id: str, ctx: MiniappDep, session: SessionDep, redis: RedisDep, cache: SlotCacheDep
) -> None:
    await ClientBookingService(session, redis, cache).release_hold(ctx.identity.client, hold_id)


@router.post("/bookings", response_model=BookingOut, status_code=201, responses=ERRORS)
async def create_booking(
    body: BookingCreateIn,
    response: Response,
    ctx: MiniappDep,
    session: SessionDep,
    redis: RedisDep,
    cache: SlotCacheDep,
    now: NowDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", max_length=64)],
) -> BookingOut:
    """Confirms a hold. Retrying with the same Idempotency-Key returns the same booking (200)."""
    result = await ClientBookingService(session, redis, cache).create(
        ctx.branch_id,
        ctx.identity.client,
        ctx.actor,
        hold_id=body.hold_id,
        comment=body.comment,
        bonus_to_spend=body.bonus_to_spend,
        idempotency_key=idempotency_key,
        now=now,
    )
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return await _one(ctx, session, result.booking, now)


@router.get("/bookings", response_model=BookingPage, responses=ERRORS)
async def list_bookings(
    ctx: MiniappDep,
    session: SessionDep,
    redis: RedisDep,
    cache: SlotCacheDep,
    now: NowDep,
    scope: Literal["upcoming", "past"] = "upcoming",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: str | None = None,
) -> BookingPage:
    items, next_cursor = await ClientBookingService(session, redis, cache).list(
        ctx.identity.client, upcoming=scope == "upcoming", now=now, limit=limit, cursor=cursor
    )
    salon = await BranchService(session).settings(ctx.branch_id)
    return BookingPage(
        items=await client_bookings_out(session, items, salon, now), next_cursor=next_cursor
    )


@router.get("/bookings/repeat", response_model=RepeatDraftOut | None, responses=ERRORS)
async def repeat_last(
    ctx: MiniappDep, session: SessionDep, redis: RedisDep, cache: SlotCacheDep, now: NowDep
) -> RepeatDraftOut | None:
    """'Same as last time': barber and services of the last visit, if still bookable."""
    last = await ClientBookingService(session, redis, cache).last_visit(ctx.identity.client, now)
    if last is None:
        return None
    barber = await BarberRepository(session).get(ctx.branch_id, last.barber_id)
    if barber is not None and not (barber.is_active and barber.is_bookable_online):
        barber = None
    wanted = [line.service_id for line in last.services if line.service_id is not None]
    offered: set[uuid.UUID] = set()
    if barber is not None:
        pairs = await BarberServiceRepository(session).list_with_services(
            [barber.id], only_active=True
        )
        offered = {service.id for _, service in pairs}
    available = [sid for sid in wanted if barber is None or sid in offered]
    return RepeatDraftOut(
        source_booking_id=last.id,
        barber=to_public_barber(barber) if barber else None,
        service_ids=available,
        missing_service_ids=[sid for sid in wanted if sid not in available],
    )


@router.get("/bookings/{booking_id}", response_model=BookingOut, responses=ERRORS)
async def get_booking(
    booking_id: uuid.UUID,
    ctx: MiniappDep,
    session: SessionDep,
    redis: RedisDep,
    cache: SlotCacheDep,
    now: NowDep,
) -> BookingOut:
    booking = await ClientBookingService(session, redis, cache).get(ctx.identity.client, booking_id)
    return await _one(ctx, session, booking, now)


@router.post("/bookings/{booking_id}/cancel", response_model=BookingOut, responses=ERRORS)
async def cancel_booking(
    booking_id: uuid.UUID,
    body: CancelIn,
    ctx: MiniappDep,
    session: SessionDep,
    redis: RedisDep,
    cache: SlotCacheDep,
    now: NowDep,
) -> BookingOut:
    booking = await ClientBookingService(session, redis, cache).cancel(
        ctx.branch_id, ctx.identity.client, ctx.actor, booking_id, body.reason, now
    )
    return await _one(ctx, session, booking, now)


@router.post("/bookings/{booking_id}/reschedule", response_model=BookingOut, responses=ERRORS)
async def reschedule_booking(
    booking_id: uuid.UUID,
    body: RescheduleIn,
    ctx: MiniappDep,
    session: SessionDep,
    redis: RedisDep,
    cache: SlotCacheDep,
    now: NowDep,
) -> BookingOut:
    """Move to a new time using a hold placed with `reschedule_booking_id`."""
    booking = await ClientBookingService(session, redis, cache).reschedule(
        ctx.branch_id, ctx.identity.client, ctx.actor, booking_id, body.hold_id, now
    )
    return await _one(ctx, session, booking, now)
