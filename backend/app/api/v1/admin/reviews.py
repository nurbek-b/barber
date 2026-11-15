"""Review moderation: list reviews of the salon's barbers and hide or show them."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import AdminContext, SessionDep, require
from app.core.errors import ErrorResponse
from app.models import Barber, Booking, Client
from app.schemas.catalog import AdminReviewOut, ReviewVisibilityIn
from app.schemas.common import Page
from app.services.permissions import Perm
from app.services.reviews import ReviewService

router = APIRouter(prefix="/reviews", tags=["admin-reviews"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
}

CanRead = Annotated[AdminContext, Depends(require(Perm.BARBERS_READ))]
CanModerate = Annotated[AdminContext, Depends(require(Perm.BARBERS_WRITE))]


def to_out(booking: Booking, client_name: str, barber_name: str) -> AdminReviewOut:
    return AdminReviewOut(
        booking_id=booking.id,
        barber_id=booking.barber_id,
        barber_name=barber_name,
        client_id=booking.client_id,
        client_name=client_name,
        rating=booking.rating or 0,
        text=booking.review_text,
        hidden=booking.review_hidden,
        created_at=booking.rated_at or booking.end_at,
    )


@router.get("", response_model=Page[AdminReviewOut], responses=ERRORS)
async def list_reviews(
    ctx: CanRead,
    session: SessionDep,
    barber_id: uuid.UUID | None = None,
    hidden: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AdminReviewOut]:
    rows, total = await ReviewService(session).admin_page(
        ctx.branch_id, barber_id=barber_id, hidden=hidden, limit=limit, offset=offset
    )
    return Page(items=[to_out(*row) for row in rows], total=total, limit=limit, offset=offset)


@router.post("/{booking_id}/visibility", response_model=AdminReviewOut, responses=ERRORS)
async def set_visibility(
    booking_id: uuid.UUID, body: ReviewVisibilityIn, ctx: CanModerate, session: SessionDep
) -> AdminReviewOut:
    """Hidden reviews leave the public feed and the barber's average rating."""
    booking = await ReviewService(session).set_hidden(
        ctx.branch_id, booking_id, body.hidden, ctx.actor
    )
    barber = await session.get(Barber, booking.barber_id)
    client = await session.get(Client, booking.client_id) if booking.client_id else None
    return to_out(booking, client.name if client else "", barber.name if barber else "")
