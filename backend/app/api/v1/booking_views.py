"""Response builders for bookings (shared by Mini App and admin routers)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.pricing import Quote
from app.models import Barber, Booking, Client, SalonSettings
from app.models.enums import BookingStatus
from app.repositories.bookings import BookingRepository
from app.schemas.bookings import (
    AdminBookingOut,
    AdminClientRef,
    BookingBarberOut,
    BookingOut,
    BookingServiceOut,
    QuoteLineOut,
    QuoteOut,
)
from app.services.bookings import can_change
from app.services.payments import amount_left, payment_status
from app.services.reviews import can_review


def quote_out(quote: Quote, promo_code: str | None = None) -> QuoteOut:
    return QuoteOut(
        lines=[
            QuoteLineOut(
                service_id=line.service_id,
                name_i18n=line.name,
                duration_min=line.duration_min,
                price=line.price,
            )
            for line in quote.lines
        ],
        subtotal=quote.subtotal,
        duration_min=quote.duration_min,
        bonus_balance=quote.bonus_balance,
        max_bonus_spend=quote.max_bonus_spend,
        discount=quote.discount,
        promo_code=promo_code,
    )


def _barber_ref(barber: Barber | None, barber_id: uuid.UUID) -> BookingBarberOut:
    if barber is None:
        return BookingBarberOut(id=barber_id, name="", photo_url=None)
    return BookingBarberOut(id=barber.id, name=barber.name, photo_url=barber.photo_url)


def _services(booking: Booking) -> list[BookingServiceOut]:
    return [
        BookingServiceOut(
            service_id=line.service_id,
            name_i18n=line.name_snapshot,
            duration_min=line.duration_min,
            price=line.price,
        )
        for line in booking.services
    ]


def _can_pay(booking: Booking, barber: Barber | None, salon: SalonSettings) -> bool:
    has_qr = bool((barber.payment_qr_url if barber else None) or salon.payment_qr_url)
    return (
        has_qr
        and booking.status in (BookingStatus.PENDING, BookingStatus.CONFIRMED)
        and booking.total_due > booking.prepaid_amount
        and amount_left(booking) > 0
    )


async def client_bookings_out(
    session: AsyncSession, bookings: Sequence[Booking], salon: SalonSettings, now: datetime
) -> list[BookingOut]:
    barbers = await BookingRepository(session).barbers_by_id([b.barber_id for b in bookings])
    return [
        BookingOut(
            id=booking.id,
            status=booking.status,
            barber=_barber_ref(barbers.get(booking.barber_id), booking.barber_id),
            services=_services(booking),
            start_at=booking.start_at,
            end_at=booking.end_at,
            subtotal=booking.subtotal,
            bonus_spent=booking.bonus_spent,
            discount=booking.discount,
            total_due=booking.total_due,
            comment=booking.comment,
            can_cancel=can_change(booking, now, salon.cancel_min_hours),
            can_reschedule=can_change(booking, now, salon.reschedule_min_hours),
            created_at=booking.created_at,
            rating=booking.rating,
            review_text=None if booking.review_hidden else booking.review_text,
            can_review=can_review(booking, now),
            prepaid_amount=booking.prepaid_amount,
            prepay_due=booking.prepay_due,
            payment_status=payment_status(booking),
            can_pay=_can_pay(booking, barbers.get(booking.barber_id), salon),
        )
        for booking in bookings
    ]


async def admin_bookings_out(
    session: AsyncSession, bookings: Sequence[Booking]
) -> list[AdminBookingOut]:
    repo = BookingRepository(session)
    barbers = await repo.barbers_by_id([b.barber_id for b in bookings])
    clients: dict[uuid.UUID, Client] = await repo.clients_by_id(
        [b.client_id for b in bookings if b.client_id]
    )
    result = []
    for booking in bookings:
        client = clients.get(booking.client_id) if booking.client_id else None
        result.append(
            AdminBookingOut(
                id=booking.id,
                kind=booking.kind,
                status=booking.status,
                source=booking.source,
                barber=_barber_ref(barbers.get(booking.barber_id), booking.barber_id),
                client=AdminClientRef(id=client.id, name=client.name, phone=client.phone)
                if client
                else None,
                services=_services(booking),
                start_at=booking.start_at,
                end_at=booking.end_at,
                subtotal=booking.subtotal,
                bonus_spent=booking.bonus_spent,
                discount=booking.discount,
                total_due=booking.total_due,
                paid_amount=booking.paid_amount,
                payment_method=booking.payment_method,
                comment=booking.comment,
                admin_note=booking.admin_note,
                cancel_reason=booking.cancel_reason,
                version=booking.version,
                created_at=booking.created_at,
                client_confirmed_at=booking.client_confirmed_at,
                prepaid_amount=booking.prepaid_amount,
                prepay_due=booking.prepay_due,
                payment_status=payment_status(booking),
            )
        )
    return result
