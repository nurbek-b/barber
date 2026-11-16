"""The barber's side of the bot: day agenda (/today, /tomorrow, morning digest) and finishing
a visit from Telegram. A barber is recognised by the chat linked through the staff link
(barbers.telegram_chat_id); completing uses the admin service with the barber role, so the
rules are the same as in the admin panel (own bookings only, not in the future).
"""

from __future__ import annotations

import html
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.domain.slots import local_day_bounds
from app.models import Barber, Booking, Client, SalonSettings
from app.models.enums import (
    ActorType,
    AdminRole,
    BookingKind,
    BookingStatus,
    PaymentMethod,
)
from app.notify.templates import format_money
from app.schemas.bookings import StatusChangeIn
from app.services.admin_bookings import AdminBookingService
from app.services.audit import Actor
from app.services.branches import BranchService
from app.services.slot_cache import SlotCache

SHOWN = (BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.COMPLETED)
ICONS = {BookingStatus.COMPLETED: "✔️", BookingStatus.PENDING: "⏳"}


@dataclass(frozen=True, slots=True)
class AgendaItem:
    booking: Booking
    client_name: str


@dataclass(frozen=True, slots=True)
class Agenda:
    barber: Barber
    salon: SalonSettings
    day: date
    items: list[AgendaItem]

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.salon.timezone)

    def lines(self, lang: str, *, markup: bool = True) -> str:
        """'10:00–11:00 ✓ Айбек · Стрижка' per visit.

        markup=True: HTML-escaped with bold names (sent directly); False: plain text for
        outbox templates, which escape placeholder values themselves.
        """
        rows = []
        for item in self.items:
            booking = item.booking
            start = booking.start_at.astimezone(self.tz).strftime("%H:%M")
            end = booking.end_at.astimezone(self.tz).strftime("%H:%M")
            mark = ICONS.get(booking.status) or ("✓" if booking.client_confirmed_at else "•")
            services = ", ".join(
                line.name_snapshot.get(lang) or line.name_snapshot.get("ru", "")
                for line in booking.services
            )
            name = item.client_name or "—"
            if markup:
                rows.append(
                    f"{start}–{end} {mark} <b>{html.escape(name)}</b> · {html.escape(services)}"
                )
            else:
                rows.append(f"{start}–{end} {mark} {name} · {services}")
        return "\n".join(rows)

    def finishable(self, now: datetime) -> list[AgendaItem]:
        """Visits the barber can finish now: started and not yet closed."""
        return [
            item
            for item in self.items
            if item.booking.status in (BookingStatus.PENDING, BookingStatus.CONFIRMED)
            and item.booking.start_at <= now
        ]


class BarberBot:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.branches = BranchService(session)

    async def barber_of_chat(self, chat_id: int) -> Barber | None:
        barber: Barber | None = await self.session.scalar(
            select(Barber).where(Barber.telegram_chat_id == chat_id, Barber.is_active.is_(True))
        )
        return barber

    async def agenda(self, barber: Barber, day: date) -> Agenda:
        salon = await self.branches.settings(barber.branch_id)
        bounds = local_day_bounds(day, ZoneInfo(salon.timezone))
        rows = await self.session.execute(
            select(Booking, Client.name)
            .options(selectinload(Booking.services))
            .outerjoin(Client, Client.id == Booking.client_id)
            .where(
                Booking.barber_id == barber.id,
                Booking.kind == BookingKind.APPOINTMENT,
                Booking.status.in_(SHOWN),
                Booking.start_at >= bounds.start,
                Booking.start_at < bounds.end,
            )
            .order_by(Booking.start_at)
        )
        items = [AgendaItem(booking, name or "") for booking, name in rows.all()]
        return Agenda(barber=barber, salon=salon, day=day, items=items)

    async def complete(
        self,
        barber: Barber,
        booking_id: uuid.UUID,
        method: PaymentMethod,
        now: datetime,
        redis: Redis | None,
    ) -> tuple[Booking, str]:
        """Finish a visit paid in full with `method`. Raises AppError with a code on refusal."""
        booking = await self.session.get(Booking, booking_id)
        if booking is None or booking.barber_id != barber.id:
            raise AppError("Not your booking", code="not_found")
        service = AdminBookingService(self.session, redis, SlotCache(redis))
        done = await service.change_status(
            barber.branch_id,
            booking_id,
            StatusChangeIn(
                version=booking.version, status=BookingStatus.COMPLETED, payment_method=method
            ),
            Actor(type=ActorType.SYSTEM, id=None),
            AdminRole.BARBER,
            barber.id,
            now,
        )
        salon = await self.branches.settings(barber.branch_id)
        return done, format_money(done.paid_amount or 0, salon.currency)
