from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from pydantic import Field

from app.api.deps import AdminContext, SessionDep, SettingsDep, ensure_own_barber, require
from app.core.errors import ErrorResponse
from app.models import Barber
from app.schemas.catalog import (
    BarberDetailOut,
    BarberIn,
    BarberOut,
    BarberPatch,
    BarberServiceOut,
    BarberServicesPut,
)
from app.schemas.common import ApiModel, Page
from app.services.barbers import BarberServiceView, BarbersService
from app.services.permissions import Perm
from app.services.staff_link import make_token

router = APIRouter(prefix="/barbers", tags=["admin-barbers"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

CanRead = Annotated[AdminContext, Depends(require(Perm.BARBERS_READ, Perm.BARBERS_READ_OWN))]
CanWrite = Annotated[AdminContext, Depends(require(Perm.BARBERS_WRITE))]


def to_out(barber: Barber) -> BarberOut:
    return BarberOut(
        id=barber.id,
        name=barber.name,
        photo_url=barber.photo_url,
        specialization_i18n=barber.specialization_i18n,
        bio_i18n=barber.bio_i18n,
        rating=barber.rating_x100 / 100 if barber.rating_count else None,
        rating_count=barber.rating_count,
        sort_order=barber.sort_order,
        is_active=barber.is_active,
        is_bookable_online=barber.is_bookable_online,
        telegram_chat_id=barber.telegram_chat_id,
    )


def to_service_out(view: BarberServiceView) -> BarberServiceOut:
    return BarberServiceOut(
        service_id=view.link.service_id,
        price=view.link.price,
        duration_min=view.link.duration_min,
        is_active=view.link.is_active,
        effective_price=view.effective_price,
        effective_duration_min=view.effective_duration_min,
    )


async def _detail(service: BarbersService, barber: Barber) -> BarberDetailOut:
    views = await service.services_of(barber.id)
    return BarberDetailOut(
        **to_out(barber).model_dump(), services=[to_service_out(view) for view in views]
    )


@router.get("", response_model=Page[BarberOut], responses=ERRORS)
async def list_barbers(
    ctx: CanRead,
    session: SessionDep,
    only_active: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[BarberOut]:
    ids = None
    if not ctx.can(Perm.BARBERS_READ):  # barber role: only themselves
        ids = [ctx.admin.barber_id] if ctx.admin.barber_id else []
    items, total = await BarbersService(session).list_page(
        ctx.branch_id, only_active=only_active, ids=ids, limit=limit, offset=offset
    )
    return Page(items=[to_out(item) for item in items], total=total, limit=limit, offset=offset)


@router.post(
    "", response_model=BarberDetailOut, status_code=status.HTTP_201_CREATED, responses=ERRORS
)
async def create_barber(body: BarberIn, ctx: CanWrite, session: SessionDep) -> BarberDetailOut:
    service = BarbersService(session)
    barber = await service.create(ctx.branch_id, body, ctx.actor)
    return await _detail(service, barber)


@router.get("/{barber_id}", response_model=BarberDetailOut, responses=ERRORS)
async def get_barber(barber_id: uuid.UUID, ctx: CanRead, session: SessionDep) -> BarberDetailOut:
    ensure_own_barber(ctx, barber_id, Perm.BARBERS_READ)
    service = BarbersService(session)
    return await _detail(service, await service.get(ctx.branch_id, barber_id))


@router.patch("/{barber_id}", response_model=BarberDetailOut, responses=ERRORS)
async def update_barber(
    barber_id: uuid.UUID, body: BarberPatch, ctx: CanWrite, session: SessionDep
) -> BarberDetailOut:
    service = BarbersService(session)
    barber = await service.update(ctx.branch_id, barber_id, body, ctx.actor)
    return await _detail(service, barber)


@router.delete("/{barber_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
async def deactivate_barber(barber_id: uuid.UUID, ctx: CanWrite, session: SessionDep) -> None:
    await BarbersService(session).deactivate(ctx.branch_id, barber_id, ctx.actor)


@router.put("/{barber_id}/services", response_model=list[BarberServiceOut], responses=ERRORS)
async def replace_barber_services(
    barber_id: uuid.UUID, body: BarberServicesPut, ctx: CanWrite, session: SessionDep
) -> list[BarberServiceOut]:
    views = await BarbersService(session).replace_services(
        ctx.branch_id, barber_id, body.services, ctx.actor
    )
    return [to_service_out(view) for view in views]


class TelegramLinkOut(ApiModel):
    link: str = Field(description="Send to the barber: opening it links their Telegram chat")
    expires_at: datetime


@router.get("/{barber_id}/telegram-link", response_model=TelegramLinkOut, responses=ERRORS)
async def telegram_link(
    barber_id: uuid.UUID, ctx: CanWrite, session: SessionDep, settings: SettingsDep
) -> TelegramLinkOut:
    """Deep link t.me/<bot>?start=b_<signed token>; valid for STAFF_LINK_TTL_SECONDS."""
    barber = await BarbersService(session).get(ctx.branch_id, barber_id)
    now = datetime.now(UTC)
    token = make_token(barber.id, settings.jwt_secret.get_secret_value(), now)
    return TelegramLinkOut(
        link=f"https://t.me/{settings.bot_username}?start={token}",
        expires_at=now + timedelta(seconds=settings.staff_link_ttl_seconds),
    )


@router.post("/{barber_id}/photo", response_model=BarberOut, responses=ERRORS)
async def upload_photo(
    barber_id: uuid.UUID,
    ctx: CanWrite,
    session: SessionDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="JPEG, PNG or WebP, up to 5 MB")],
) -> BarberOut:
    content = await file.read(settings.max_upload_bytes + 1)
    barber = await BarbersService(session, settings).set_photo(
        ctx.branch_id, barber_id, content, ctx.actor
    )
    return to_out(barber)
