"""Barber reviews: a star rating (1..5) and optional text, one per completed visit.

A review lives on its booking (rating / rated_at / review_text / review_hidden), so it can only
come from a client who actually visited that barber. The salon may hide a review (abuse, spam):
hidden reviews leave the public feed and the barber's average.
"""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError, ValidationAppError
from app.models import Barber, Booking, Client
from app.models.enums import BookingStatus
from app.services.audit import Actor, AuditService

REVIEW_WINDOW = timedelta(days=30)
MAX_TEXT = 1000


@dataclass(frozen=True, slots=True)
class ReviewView:
    booking: Booking
    author: str


def public_author(name: str | None) -> str:
    """'Бектур Асанов' -> 'Бектур А.' — enough to feel real, not enough to identify."""
    parts = (name or "").split()
    if not parts:
        return ""
    return f"{parts[0]} {parts[1][0]}." if len(parts) > 1 else parts[0]


def can_review(booking: Booking, now: datetime) -> bool:
    if booking.status is not BookingStatus.COMPLETED or booking.review_hidden:
        return False
    return now - (booking.completed_at or booking.end_at) <= REVIEW_WINDOW


def _encode(booking: Booking) -> str:
    rated = (booking.rated_at or booking.end_at).timestamp()
    return base64.urlsafe_b64encode(f"{rated}|{booking.id}".encode()).decode()


def _decode(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    if not cursor:
        return None
    try:
        ts, _, booking_id = base64.urlsafe_b64decode(cursor.encode()).decode().partition("|")
        return datetime.fromtimestamp(float(ts), UTC), uuid.UUID(booking_id)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationAppError("Invalid cursor", code="invalid_cursor") from exc


async def recompute_barber_rating(session: AsyncSession, barber_id: uuid.UUID) -> None:
    avg, count = (
        await session.execute(
            select(func.avg(Booking.rating), func.count(Booking.rating)).where(
                Booking.barber_id == barber_id,
                Booking.rating.is_not(None),
                Booking.review_hidden.is_(False),
            )
        )
    ).one()
    await session.execute(
        update(Barber)
        .where(Barber.id == barber_id)
        .values(rating_x100=round(float(avg or 0) * 100), rating_count=int(count))
    )


class ReviewService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def submit(
        self, client: Client, booking_id: uuid.UUID, rating: int, text: str | None, now: datetime
    ) -> Booking:
        """Create or edit the client's review of their own completed visit (within 30 days)."""
        booking = await self.session.scalar(
            select(Booking)
            .where(Booking.id == booking_id, Booking.client_id == client.id)
            .with_for_update()
        )
        if booking is None:
            raise NotFoundError("Booking not found")
        if not can_review(booking, now):
            raise ValidationAppError("This visit can't be reviewed", code="review_unavailable")
        clean = (text or "").strip()[:MAX_TEXT] or None
        booking.rating = rating
        booking.review_text = clean
        booking.rated_at = now
        await self.session.flush()
        await recompute_barber_rating(self.session, booking.barber_id)
        await self.session.commit()
        return booking

    async def public_page(
        self, branch_id: uuid.UUID, barber_id: uuid.UUID, *, limit: int, cursor: str | None
    ) -> tuple[list[ReviewView], str | None]:
        """Newest first. Rating-only reviews are listed too (they count in the average)."""
        query = (
            select(Booking, Client.name)
            .options(selectinload(Booking.services))
            .outerjoin(Client, Client.id == Booking.client_id)
            .where(
                Booking.branch_id == branch_id,
                Booking.barber_id == barber_id,
                Booking.rating.is_not(None),
                Booking.review_hidden.is_(False),
            )
            .order_by(Booking.rated_at.desc(), Booking.id.desc())
            .limit(limit + 1)
        )
        after = _decode(cursor)
        if after:
            ts, last_id = after
            query = query.where(
                or_(Booking.rated_at < ts, and_(Booking.rated_at == ts, Booking.id < last_id))
            )
        rows = (await self.session.execute(query)).all()
        items = [ReviewView(booking, public_author(name)) for booking, name in rows[:limit]]
        next_cursor = _encode(items[-1].booking) if len(rows) > limit and items else None
        return items, next_cursor

    async def admin_page(
        self,
        branch_id: uuid.UUID,
        *,
        barber_id: uuid.UUID | None,
        hidden: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[list[tuple[Booking, str, str]], int]:
        """(booking, client name, barber name) — full names for the salon."""
        conditions = [Booking.branch_id == branch_id, Booking.rating.is_not(None)]
        if barber_id:
            conditions.append(Booking.barber_id == barber_id)
        if hidden is not None:
            conditions.append(Booking.review_hidden.is_(hidden))
        total = await self.session.scalar(select(func.count()).where(*conditions)) or 0
        rows = await self.session.execute(
            select(Booking, Client.name, Barber.name)
            .join(Barber, Barber.id == Booking.barber_id)
            .outerjoin(Client, Client.id == Booking.client_id)
            .where(*conditions)
            .order_by(Booking.rated_at.desc(), Booking.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [(booking, client or "", barber) for booking, client, barber in rows.all()], total

    async def set_hidden(
        self, branch_id: uuid.UUID, booking_id: uuid.UUID, hidden: bool, actor: Actor
    ) -> Booking:
        booking = await self.session.scalar(
            select(Booking)
            .where(
                Booking.id == booking_id,
                Booking.branch_id == branch_id,
                Booking.rating.is_not(None),
            )
            .with_for_update()
        )
        if booking is None:
            raise NotFoundError("Review not found")
        if booking.review_hidden != hidden:
            booking.review_hidden = hidden
            AuditService(self.session).record(
                actor,
                "review.hide" if hidden else "review.show",
                "booking",
                booking.id,
                before={"review_hidden": not hidden},
                after={"review_hidden": hidden},
            )
            await self.session.flush()
            await recompute_barber_rating(self.session, booking.barber_id)
        await self.session.commit()
        return booking
