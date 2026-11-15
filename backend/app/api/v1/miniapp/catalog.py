from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import MiniappDep, SessionDep
from app.core.errors import ErrorResponse
from app.models import Barber
from app.schemas.catalog import (
    PublicBarberOut,
    PublicCatalogOut,
    PublicServiceOut,
    ServiceCategoryOut,
)
from app.schemas.miniapp import SalonPublicOut
from app.services.barbers import BarbersService
from app.services.branches import BranchService
from app.services.catalog import CatalogService

router = APIRouter(tags=["miniapp-catalog"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
}


def to_public_barber(barber: Barber) -> PublicBarberOut:
    return PublicBarberOut(
        id=barber.id,
        name=barber.name,
        photo_url=barber.photo_url,
        specialization_i18n=barber.specialization_i18n,
        bio_i18n=barber.bio_i18n,
        rating=barber.rating_x100 / 100 if barber.rating_count else None,
        rating_count=barber.rating_count,
    )


@router.get("/salon", response_model=SalonPublicOut, responses=ERRORS)
async def get_salon(ctx: MiniappDep, session: SessionDep) -> SalonPublicOut:
    salon = await BranchService(session).settings(ctx.branch_id)
    return SalonPublicOut(
        name=salon.name,
        timezone=salon.timezone,
        currency=salon.currency,
        default_language=salon.default_language,
        slot_step_min=salon.slot_step_min,
        max_days_ahead=salon.max_days_ahead,
        cancel_min_hours=salon.cancel_min_hours,
        reschedule_min_hours=salon.reschedule_min_hours,
        contacts={str(key): str(value) for key, value in salon.contacts.items()},
        logo_url=salon.logo_url,
        gallery=list(salon.gallery or []),
    )


@router.get("/barbers", response_model=list[PublicBarberOut], responses=ERRORS)
async def list_barbers(
    ctx: MiniappDep,
    session: SessionDep,
    service_ids: Annotated[list[uuid.UUID] | None, Query(max_length=20)] = None,
) -> list[PublicBarberOut]:
    """Barbers bookable online; with service_ids — only those who perform all of them."""
    barbers = await BarbersService(session).list_public(ctx.branch_id, service_ids)
    return [to_public_barber(barber) for barber in barbers]


@router.get("/services", response_model=PublicCatalogOut, responses=ERRORS)
async def list_services(
    ctx: MiniappDep, session: SessionDep, barber_id: uuid.UUID | None = None
) -> PublicCatalogOut:
    """Without barber_id — 'any barber' mode: price and duration as min..max ranges."""
    catalog = CatalogService(session)
    views = await catalog.public_services(ctx.branch_id, barber_id)
    used_categories = {view.service.category_id for view in views}
    categories = [
        ServiceCategoryOut.model_validate(category)
        for category in await catalog.list_categories(ctx.branch_id)
        if category.id in used_categories
    ]
    return PublicCatalogOut(
        categories=categories,
        services=[
            PublicServiceOut(
                id=view.service.id,
                category_id=view.service.category_id,
                name_i18n=view.service.name_i18n,
                description_i18n=view.service.description_i18n,
                duration_min=view.duration_min,
                duration_max_min=view.duration_max_min,
                price_min=view.price_min,
                price_max=view.price_max,
            )
            for view in views
        ],
    )
