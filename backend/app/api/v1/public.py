"""Public booking page API (no Telegram): catalog, availability, and pending bookings.

Catalog and availability reuse the Mini App handlers with a context that has the default
branch and no client. Bookings: see app/services/public_booking.py for the trust model.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Literal, cast
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import Field

from app.api.deps import (
    MiniappContext,
    NowDep,
    RedisDep,
    SessionDep,
    SettingsDep,
    SlotCacheDep,
    client_ip,
)
from app.api.v1 import booking_views
from app.api.v1.miniapp import availability as mini_availability
from app.api.v1.miniapp import catalog as mini_catalog
from app.api.v1.miniapp.catalog import to_public_barber
from app.core.errors import ErrorResponse, RateLimitedError, ValidationAppError
from app.core.redis import hit_rate_limit
from app.models import Barber
from app.schemas.bookings import (
    BookingBarberOut,
    BookingServiceOut,
    QuoteOut,
    WebBookingOut,
    WebConfirmIn,
    WebHoldIn,
    WebHoldOut,
    WebPromoIn,
)
from app.schemas.catalog import (
    PublicBarberOut,
    PublicBarberProfileOut,
    PublicCatalogOut,
    ReviewPage,
)
from app.schemas.common import ApiModel
from app.schemas.miniapp import SalonPublicOut
from app.schemas.schedule import AvailabilityDaysOut, AvailabilitySlotsOut
from app.schemas.vouchers import CertificateBalanceOut
from app.services.branches import BranchService
from app.services.funnel import FunnelService
from app.services.public_booking import PublicBookingService
from app.services.vouchers import VoucherService, certificate_state

router = APIRouter(prefix="/public", tags=["public"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
}


@dataclass(frozen=True, slots=True)
class PublicContext:
    branch_id: uuid.UUID
    client_id: uuid.UUID | None = None


async def public_context(session: SessionDep) -> MiniappContext:
    branch_id = await BranchService(session).default_branch_id()
    # duck-typed: the reused handlers only read branch_id / client_id
    return cast(MiniappContext, PublicContext(branch_id))


PublicDep = Annotated[MiniappContext, Depends(public_context)]
ServiceIds = Annotated[list[uuid.UUID], Query(min_length=1, max_length=10)]


@router.get("/salon", response_model=SalonPublicOut, responses=ERRORS)
async def salon(ctx: PublicDep, session: SessionDep) -> SalonPublicOut:
    return await mini_catalog.get_salon(ctx, session)


@router.get("/barbers", response_model=list[PublicBarberOut], responses=ERRORS)
async def barbers(
    ctx: PublicDep,
    session: SessionDep,
    service_ids: Annotated[list[uuid.UUID] | None, Query(max_length=20)] = None,
) -> list[PublicBarberOut]:
    return await mini_catalog.list_barbers(ctx, session, service_ids)


@router.get("/barbers/{barber_id}", response_model=PublicBarberProfileOut, responses=ERRORS)
async def barber_profile(
    barber_id: uuid.UUID, ctx: PublicDep, session: SessionDep
) -> PublicBarberProfileOut:
    return await mini_catalog.get_barber_profile(barber_id, ctx, session)


@router.get("/barbers/{barber_id}/reviews", response_model=ReviewPage, responses=ERRORS)
async def barber_reviews(
    barber_id: uuid.UUID,
    ctx: PublicDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    cursor: str | None = None,
) -> ReviewPage:
    return await mini_catalog.list_barber_reviews(barber_id, ctx, session, limit, cursor)


@router.get("/services", response_model=PublicCatalogOut, responses=ERRORS)
async def services(
    ctx: PublicDep, session: SessionDep, barber_id: uuid.UUID | None = None
) -> PublicCatalogOut:
    return await mini_catalog.list_services(ctx, session, barber_id)


@router.get("/availability/days", response_model=AvailabilityDaysOut, responses=ERRORS)
async def days(
    ctx: PublicDep,
    session: SessionDep,
    cache: SlotCacheDep,
    redis: RedisDep,
    now: NowDep,
    service_ids: ServiceIds,
    barber_id: uuid.UUID | None = None,
) -> AvailabilityDaysOut:
    return await mini_availability.availability_days(
        ctx, session, cache, redis, now, service_ids, barber_id
    )


@router.get("/availability/slots", response_model=AvailabilitySlotsOut, responses=ERRORS)
async def slots(
    ctx: PublicDep,
    session: SessionDep,
    cache: SlotCacheDep,
    redis: RedisDep,
    now: NowDep,
    service_ids: ServiceIds,
    day: Annotated[date, Query(alias="date")],
    barber_id: uuid.UUID | None = None,
) -> AvailabilitySlotsOut:
    return await mini_availability.availability_slots(
        ctx, session, cache, redis, now, service_ids, day, barber_id
    )


@router.post("/holds", response_model=WebHoldOut, status_code=201, responses=ERRORS)
async def hold(
    body: WebHoldIn,
    request: Request,
    ctx: PublicDep,
    session: SessionDep,
    redis: RedisDep,
    cache: SlotCacheDep,
    settings: SettingsDep,
    now: NowDep,
) -> WebHoldOut:
    """Reserve the slot for 5 minutes under the visitor's name and phone."""
    if body.website:  # bots fill every field
        raise ValidationAppError("Invalid request", code="invalid_request")
    result = await PublicBookingService(session, redis, cache, settings).hold(
        ctx.branch_id,
        name=body.name,
        phone=body.phone,
        barber_id=body.barber_id,
        service_ids=body.service_ids,
        start_at=body.start_at,
        ip=client_ip(request) or "unknown",
        now=now,
    )
    placed = result.placed
    return WebHoldOut(
        hold_id=placed.hold.id,
        expires_at=placed.hold.expires_at,
        barber=to_public_barber(placed.barber),
        start_at=placed.hold.start_at,
        end_at=placed.hold.end_at,
        # bonuses belong to a verified account: never shown or spent on the web
        quote=booking_views.quote_out(placed.quote).model_copy(
            update={"bonus_balance": 0, "max_bonus_spend": 0}
        ),
        token=result.token,
    )


@router.post("/holds/promo", response_model=QuoteOut, responses=ERRORS)
async def promo(
    body: WebPromoIn,
    ctx: PublicDep,
    session: SessionDep,
    redis: RedisDep,
    cache: SlotCacheDep,
    settings: SettingsDep,
    now: NowDep,
) -> QuoteOut:
    quote, code = await PublicBookingService(session, redis, cache, settings).promo(
        ctx.branch_id, body.token, body.code, now
    )
    return booking_views.quote_out(quote, code).model_copy(
        update={"bonus_balance": 0, "max_bonus_spend": 0}
    )


@router.post("/bookings", response_model=WebBookingOut, status_code=201, responses=ERRORS)
async def confirm(
    body: WebConfirmIn,
    request: Request,
    ctx: PublicDep,
    session: SessionDep,
    redis: RedisDep,
    cache: SlotCacheDep,
    settings: SettingsDep,
    now: NowDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", max_length=64)],
) -> WebBookingOut:
    """Create the booking as *pending*: the salon confirms it by phone."""
    booking = await PublicBookingService(session, redis, cache, settings).confirm(
        ctx.branch_id,
        token=body.token,
        comment=body.comment,
        promo_code=body.promo_code,
        idempotency_key=idempotency_key,
        ip=client_ip(request) or "unknown",
        now=now,
    )
    await session.refresh(booking, ["services"])
    barber = await session.get(Barber, booking.barber_id)
    return WebBookingOut(
        id=booking.id,
        status=booking.status,
        barber=BookingBarberOut(
            id=booking.barber_id,
            name=barber.name if barber else "",
            photo_url=barber.photo_url if barber else None,
        ),
        services=[
            BookingServiceOut(
                service_id=line.service_id,
                name_i18n=line.name_snapshot,
                duration_min=line.duration_min,
                price=line.price,
            )
            for line in booking.services
        ],
        start_at=booking.start_at,
        end_at=booking.end_at,
        subtotal=booking.subtotal,
        discount=booking.discount,
        total_due=booking.total_due,
    )


@router.get("/certificates/{code}", response_model=CertificateBalanceOut, responses=ERRORS)
async def certificate_balance(
    code: str,
    request: Request,
    ctx: PublicDep,
    session: SessionDep,
    redis: RedisDep,
    now: NowDep,
) -> CertificateBalanceOut:
    """Balance of a gift certificate by its code (rate limited: codes must not be guessable)."""
    ip = client_ip(request) or "unknown"
    if await hit_rate_limit(redis, f"pub:cert:{ip}", 20, 3600):
        raise RateLimitedError("Too many attempts, try later", headers={"Retry-After": "600"})
    cert = await VoucherService(session).find_certificate(ctx.branch_id, code)
    salon = await BranchService(session).settings(ctx.branch_id)
    today = now.astimezone(ZoneInfo(salon.timezone)).date()
    return CertificateBalanceOut(
        code=cert.code,
        balance=cert.balance,
        expires_on=cert.expires_on,
        state=certificate_state(cert, today),
    )


class FunnelEventIn(ApiModel):
    session_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    source: Literal["miniapp", "web"]
    step: Literal["open", "barber", "services", "time", "confirm", "booked"]


@router.post("/events", status_code=204, responses=ERRORS)
async def track_event(
    body: FunnelEventIn,
    request: Request,
    ctx: PublicDep,
    session: SessionDep,
    redis: RedisDep,
) -> None:
    """Anonymous booking-funnel step (one per session and step; no personal data)."""
    ip = client_ip(request) or "unknown"
    if await hit_rate_limit(redis, f"pub:ev:{ip}", 300, 3600):
        return
    await FunnelService(session).track(ctx.branch_id, body.session_id, body.source, body.step)
