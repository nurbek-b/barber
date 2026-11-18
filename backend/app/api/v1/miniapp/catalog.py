from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import MiniappDep, SessionDep
from app.core.errors import ErrorResponse, NotFoundError
from app.models import Barber
from app.schemas.catalog import (
    PublicBarberOut,
    PublicBarberProfileOut,
    PublicCatalogOut,
    PublicServiceOut,
    ReviewOut,
    ReviewPage,
    ServiceCategoryOut,
)
from app.schemas.miniapp import SalonPublicOut
from app.services.barbers import BarbersService
from app.services.branches import BranchService
from app.services.catalog import CatalogService
from app.services.reviews import ReviewService, ReviewView

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
        brand_color=salon.brand_color,
        brand_color_2=salon.brand_color_2,
        brand_bg=salon.brand_bg,
        review_links={str(k): str(v) for k, v in (salon.review_links or {}).items()},
        delivery_enabled=salon.delivery_enabled,
        delivery_fee=salon.delivery_fee,
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


def to_review(view: ReviewView) -> ReviewOut:
    booking = view.booking
    return ReviewOut(
        booking_id=booking.id,
        rating=booking.rating or 0,
        text=booking.review_text,
        author=view.author,
        services=[line.name_snapshot for line in booking.services],
        created_at=booking.rated_at or booking.end_at,
    )


@router.get("/barbers/{barber_id}", response_model=PublicBarberProfileOut, responses=ERRORS)
async def get_barber_profile(
    barber_id: uuid.UUID, ctx: MiniappDep, session: SessionDep
) -> PublicBarberProfileOut:
    """Profile page: bio, rating, works catalogue. Reviews: /barbers/{id}/reviews."""
    barber = await BarbersService(session).get(ctx.branch_id, barber_id)
    if not barber.is_active or not barber.is_bookable_online:
        raise NotFoundError("Barber not found")
    return PublicBarberProfileOut(
        **to_public_barber(barber).model_dump(), portfolio=list(barber.portfolio or [])
    )


@router.get("/barbers/{barber_id}/reviews", response_model=ReviewPage, responses=ERRORS)
async def list_barber_reviews(
    barber_id: uuid.UUID,
    ctx: MiniappDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    cursor: str | None = None,
) -> ReviewPage:
    items, next_cursor = await ReviewService(session).public_page(
        ctx.branch_id, barber_id, limit=limit, cursor=cursor
    )
    return ReviewPage(items=[to_review(item) for item in items], next_cursor=next_cursor)


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
