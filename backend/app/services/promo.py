"""Promo codes: validation and the discount they give.

A use is a pending/confirmed/completed booking carrying the code, so cancelling gives the use
back. Booking creation locks the code row (FOR UPDATE) to keep max_uses exact under races.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationAppError
from app.domain.pricing import promo_discount
from app.models import Booking, Client, PromoCode, SalonSettings
from app.models.enums import BookingStatus

COUNTED = (BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.COMPLETED)


def normalize(code: str) -> str:
    return "".join(code.split()).upper()


class PromoService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _uses(self, promo_id: uuid.UUID, client_id: uuid.UUID | None = None) -> int:
        query = select(func.count()).where(
            Booking.promo_code_id == promo_id, Booking.status.in_(COUNTED)
        )
        if client_id is not None:
            query = query.where(Booking.client_id == client_id)
        return int(await self.session.scalar(query) or 0)

    async def uses(self, promo_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not promo_ids:
            return {}
        rows = await self.session.execute(
            select(Booking.promo_code_id, func.count())
            .where(Booking.promo_code_id.in_(promo_ids), Booking.status.in_(COUNTED))
            .group_by(Booking.promo_code_id)
        )
        return {promo_id: int(count) for promo_id, count in rows.all()}

    async def resolve(
        self,
        code: str,
        client: Client,
        salon: SalonSettings,
        subtotal: int,
        now: datetime,
        *,
        lock: bool = False,
    ) -> tuple[PromoCode, int]:
        """The code and its discount for this client and check, or ValidationAppError with a
        code the Mini App translates (promo_not_found, promo_expired, ...)."""
        query = select(PromoCode).where(
            PromoCode.branch_id == salon.branch_id,
            func.upper(PromoCode.code) == normalize(code),
            PromoCode.is_active.is_(True),
        )
        if lock:
            query = query.with_for_update()
        promo = await self.session.scalar(query)
        if promo is None:
            raise ValidationAppError("Promo code not found", code="promo_not_found")
        today = now.astimezone(ZoneInfo(salon.timezone)).date()
        if promo.valid_from and today < promo.valid_from:
            raise ValidationAppError("Promo code is not active yet", code="promo_not_started")
        if promo.valid_to and today > promo.valid_to:
            raise ValidationAppError("Promo code has expired", code="promo_expired")
        if subtotal < promo.min_subtotal:
            raise ValidationAppError(
                "The order is too small for this code",
                code="promo_min_subtotal",
                details={"min_subtotal": promo.min_subtotal},
            )
        if promo.max_uses is not None and await self._uses(promo.id) >= promo.max_uses:
            raise ValidationAppError("Promo code is used up", code="promo_used_up")
        if await self._uses(promo.id, client.id) >= promo.max_uses_per_client:
            raise ValidationAppError("You have already used this code", code="promo_already_used")
        if promo.first_visit_only:
            visited = await self.session.scalar(
                select(func.count()).where(
                    Booking.client_id == client.id, Booking.status == BookingStatus.COMPLETED
                )
            )
            if visited:
                raise ValidationAppError("Only for the first visit", code="promo_first_visit")
        discount = promo_discount(promo.kind.value, promo.value, promo.max_discount, subtotal)
        return promo, discount
