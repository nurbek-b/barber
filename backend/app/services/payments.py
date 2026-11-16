"""Payments for bookings by bank QR: prepayment for unreliable clients and voluntary prepaying.

There is no payment provider: the client scans the barber's (or the salon's) bank QR, pays in
their bank app and taps "I paid". That creates a CLAIMED payment and alerts the admin chat; the
salon checks its bank app and confirms (possibly with the amount actually received) or rejects.
Confirmed money accumulates in `bookings.prepaid_amount`. A booking that required prepayment
stays PENDING until enough is confirmed, then becomes CONFIRMED and the client is told.

When the visit is completed the admin still records the full `paid_amount` (prepayment
included) as before, so revenue reports do not change.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.models import (
    Barber,
    Booking,
    Client,
    Notification,
    Payment,
    SalonSettings,
    TelegramOutbox,
    User,
)
from app.models.enums import (
    ActorType,
    BookingKind,
    BookingStatus,
    NotificationType,
    PaymentMethod,
    PaymentStatus,
)
from app.notify.templates import format_money
from app.services.audit import Actor, AuditService
from app.services.branches import BranchService

OPEN_STATUSES = (BookingStatus.PENDING, BookingStatus.CONFIRMED)
MAX_OPEN_CLAIMS = 3


def requires_prepay(salon: SalonSettings, client: Client) -> bool:
    """Prepayment is on (percent > 0) and the client is flagged or missed enough visits."""
    if salon.prepay_percent <= 0:
        return False
    return client.prepay_required or client.no_show_count >= max(1, salon.prepay_after_no_shows)


def prepay_amount(salon: SalonSettings, total_due: int) -> int:
    """`prepay_percent` of the total, rounded up to whole som (tyiyn are not in bank QR apps)."""
    if total_due <= 0 or salon.prepay_percent <= 0:
        return 0
    raw = -(-total_due * salon.prepay_percent // 100)
    return min(total_due, -(-raw // 100) * 100)


def payment_status(booking: Booking) -> str:
    """unpaid | claimed | partial | paid — for badges in the apps."""
    paid = booking.paid_amount if booking.status is BookingStatus.COMPLETED else None
    received = max(booking.prepaid_amount, paid or 0)
    if booking.total_due > 0 and received >= booking.total_due:
        return "paid"
    if received > 0:
        return "partial"
    if booking.payment_claimed_at is not None:
        return "claimed"
    return "unpaid"


def amount_left(booking: Booking) -> int:
    """What the client can still pay online: the prepayment first, otherwise the rest."""
    if booking.prepay_due > booking.prepaid_amount:
        return booking.prepay_due - booking.prepaid_amount
    return max(0, booking.total_due - booking.prepaid_amount)


@dataclass(frozen=True, slots=True)
class PaymentInfo:
    booking: Booking
    qr_url: str | None
    note: str | None
    currency: str
    amount_left: int
    claimed: bool


class PaymentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ client side

    async def _client_booking(self, client: Client, booking_id: uuid.UUID) -> Booking:
        booking = await self.session.scalar(
            select(Booking)
            .where(Booking.id == booking_id, Booking.client_id == client.id)
            .with_for_update()
        )
        if booking is None or booking.kind is not BookingKind.APPOINTMENT:
            raise NotFoundError("Booking not found")
        return booking

    async def info(self, client: Client, booking_id: uuid.UUID) -> PaymentInfo:
        booking = await self._client_booking(client, booking_id)
        return await self._info(booking)

    async def _info(self, booking: Booking) -> PaymentInfo:
        salon = await BranchService(self.session).settings(booking.branch_id)
        barber = await self.session.get(Barber, booking.barber_id)
        qr = (barber.payment_qr_url if barber else None) or salon.payment_qr_url
        return PaymentInfo(
            booking=booking,
            qr_url=qr,
            note=salon.payment_note,
            currency=salon.currency,
            amount_left=amount_left(booking),
            claimed=booking.payment_claimed_at is not None,
        )

    async def claim(
        self, client: Client, booking_id: uuid.UUID, amount: int, now: datetime
    ) -> tuple[PaymentInfo, Notification]:
        booking = await self._client_booking(client, booking_id)
        if booking.status not in OPEN_STATUSES or booking.start_at <= now - timedelta(hours=12):
            raise ValidationAppError("This booking can't be paid online", code="payment_closed")
        info = await self._info(booking)
        if info.qr_url is None:
            raise ValidationAppError("The salon doesn't accept QR payments", code="no_payment_qr")
        remaining = booking.total_due - booking.prepaid_amount
        if remaining <= 0:
            raise ValidationAppError("The booking is already paid", code="already_paid")
        if not 0 < amount <= remaining:
            raise ValidationAppError(
                "Check the amount", code="bad_amount", details={"max": remaining}
            )
        open_claims = await self.session.scalar(
            select(Payment.id)
            .where(Payment.booking_id == booking.id, Payment.status == PaymentStatus.CLAIMED)
            .offset(MAX_OPEN_CLAIMS - 1)
            .limit(1)
        )
        if open_claims is not None:
            raise ConflictError("Wait until the salon checks your payment", code="claim_pending")

        payment = Payment(
            branch_id=booking.branch_id,
            booking_id=booking.id,
            amount=amount,
            method=PaymentMethod.TRANSFER,
            status=PaymentStatus.CLAIMED,
            by_client=True,
        )
        self.session.add(payment)
        booking.payment_claimed_at = now
        await self.session.flush()
        actor = Actor(type=ActorType.CLIENT, id=client.id)
        self.audit.record(actor, "payment.claim", "booking", booking.id, after={"amount": amount})
        notification = await self._notify_admin(booking, client, payment, now)
        await self.session.commit()
        return await self._info(booking), notification

    async def _notify_admin(
        self, booking: Booking, client: Client, payment: Payment, now: datetime
    ) -> Notification:
        salon = await BranchService(self.session).settings(booking.branch_id)
        barber = await self.session.get(Barber, booking.barber_id)
        tz = ZoneInfo(salon.timezone)
        values: dict[str, Any] = {
            "booking_id": str(booking.id),
            "payment_id": str(payment.id),
            "client": client.name,
            "phone": client.phone or "",
            "barber": barber.name if barber else "",
            "when": booking.start_at.astimezone(tz).strftime("%d.%m.%Y %H:%M"),
            "amount": format_money(payment.amount, salon.currency),
            "amount_raw": payment.amount,
            "total_due": format_money(booking.total_due, salon.currency),
        }
        notification = Notification(
            branch_id=booking.branch_id,
            type=NotificationType.PAYMENT_CLAIMED,
            booking_id=booking.id,
            payload=values,
            created_at=now,
        )
        self.session.add(notification)
        if salon.admin_chat_id:
            self.session.add(
                TelegramOutbox(
                    chat_id=salon.admin_chat_id,
                    template_key="payment_claimed_admin",
                    language=salon.default_language,
                    payload=values,
                    booking_id=booking.id,
                )
            )
        await self.session.flush()
        return notification

    # ------------------------------------------------------------------ salon side

    async def list_for_booking(self, branch_id: uuid.UUID, booking_id: uuid.UUID) -> list[Payment]:
        await self._branch_booking(branch_id, booking_id, lock=False)
        rows = await self.session.scalars(
            select(Payment)
            .where(Payment.booking_id == booking_id)
            .order_by(Payment.created_at.desc())
        )
        return list(rows)

    async def _branch_booking(
        self, branch_id: uuid.UUID, booking_id: uuid.UUID, *, lock: bool = True
    ) -> Booking:
        query = select(Booking).where(Booking.id == booking_id, Booking.branch_id == branch_id)
        booking = await self.session.scalar(query.with_for_update() if lock else query)
        if booking is None or booking.kind is not BookingKind.APPOINTMENT:
            raise NotFoundError("Booking not found")
        return booking

    async def add(
        self,
        branch_id: uuid.UUID,
        booking_id: uuid.UUID,
        *,
        amount: int,
        method: PaymentMethod,
        note: str | None,
        actor: Actor,
        now: datetime,
    ) -> Payment:
        """A payment the salon received itself (deposit in cash, transfer it saw)."""
        booking = await self._branch_booking(branch_id, booking_id)
        payment = Payment(
            branch_id=branch_id,
            booking_id=booking.id,
            amount=amount,
            method=method,
            status=PaymentStatus.CONFIRMED,
            note=(note or "").strip() or None,
            decided_at=now,
            decided_by=actor.id,
        )
        self.session.add(payment)
        await self.session.flush()
        await self._apply(booking, payment, actor, now)
        await self.session.commit()
        return payment

    async def decide(
        self,
        branch_id: uuid.UUID,
        payment_id: uuid.UUID,
        *,
        confirm: bool,
        amount: int | None,
        actor: Actor,
        now: datetime,
    ) -> Payment:
        payment = await self.session.scalar(
            select(Payment)
            .where(Payment.id == payment_id, Payment.branch_id == branch_id)
            .with_for_update()
        )
        if payment is None or payment.booking_id is None:
            raise NotFoundError("Payment not found")
        if payment.status is not PaymentStatus.CLAIMED:
            raise ConflictError("The payment was already checked", code="payment_decided")
        booking = await self._branch_booking(branch_id, payment.booking_id)
        payment.decided_at = now
        payment.decided_by = actor.id
        if confirm:
            if amount is not None:
                payment.amount = amount
            payment.status = PaymentStatus.CONFIRMED
            await self.session.flush()
            await self._apply(booking, payment, actor, now)
        else:
            payment.status = PaymentStatus.REJECTED
            self.audit.record(
                actor, "payment.reject", "booking", booking.id, after={"amount": payment.amount}
            )
            await self.session.flush()
            await self._sync_claimed(booking)
            await self._tell_client(booking, "payment_rejected_client", payment)
        await self.session.commit()
        return payment

    async def _sync_claimed(self, booking: Booking) -> None:
        still_open = await self.session.scalar(
            select(Payment.created_at)
            .where(Payment.booking_id == booking.id, Payment.status == PaymentStatus.CLAIMED)
            .order_by(Payment.created_at)
            .limit(1)
        )
        booking.payment_claimed_at = still_open

    async def _apply(self, booking: Booking, payment: Payment, actor: Actor, now: datetime) -> None:
        before = {"prepaid_amount": booking.prepaid_amount, "status": booking.status.value}
        booking.prepaid_amount += payment.amount
        await self._sync_claimed(booking)
        confirmed = (
            booking.status is BookingStatus.PENDING
            and booking.prepay_due > 0
            and booking.prepaid_amount >= booking.prepay_due
        )
        if confirmed:
            booking.status = BookingStatus.CONFIRMED
            booking.version += 1
        self.audit.record(
            actor,
            "payment.confirm",
            "booking",
            booking.id,
            before=before,
            after={
                "prepaid_amount": booking.prepaid_amount,
                "status": booking.status.value,
                "amount": payment.amount,
            },
        )
        await self.session.flush()
        if payment.by_client or confirmed:
            await self._tell_client(
                booking,
                "payment_confirmed_booking_client" if confirmed else "payment_confirmed_client",
                payment,
            )

    async def _tell_client(self, booking: Booking, template: str, payment: Payment) -> None:
        client = await self.session.get(Client, booking.client_id) if booking.client_id else None
        user = await self.session.get(User, client.user_id) if client and client.user_id else None
        if client is None or user is None or user.bot_blocked:
            return
        salon = await BranchService(self.session).settings(booking.branch_id)
        tz = ZoneInfo(salon.timezone)
        self.session.add(
            TelegramOutbox(
                chat_id=user.telegram_id,
                template_key=template,
                language=client.language,
                booking_id=booking.id,
                payload={
                    "amount": format_money(payment.amount, salon.currency),
                    "when": booking.start_at.astimezone(tz).strftime("%d.%m.%Y %H:%M"),
                    "salon": salon.name,
                },
            )
        )
        await self.session.flush()


def _pay_button(lang: str, booking_id: uuid.UUID) -> dict[str, str]:
    from app.bot.texts import t  # local import: keeps services free of bot imports at load
    from app.core.config import get_settings

    settings = get_settings()
    param = f"pay_{booking_id}"
    label = t("pay_now", lang)
    if settings.miniapp_url:
        sep = "&" if "?" in settings.miniapp_url else "?"
        return {"text": label, "web_app": f"{settings.miniapp_url}{sep}startapp={param}"}
    link = f"https://t.me/{settings.bot_username}/{settings.miniapp_short_name}?startapp={param}"
    return {"text": label, "url": link}


async def request_prepayment(
    session: AsyncSession, booking: Booking, salon: SalonSettings, client: Client
) -> None:
    """Tell the client the booking waits for a prepayment (instead of "You're booked")."""
    user = await session.get(User, client.user_id) if client.user_id else None
    if user is None or user.bot_blocked:
        return
    tz = ZoneInfo(salon.timezone)
    session.add(
        TelegramOutbox(
            chat_id=user.telegram_id,
            template_key="booking_prepay_client",
            language=client.language,
            booking_id=booking.id,
            payload={
                "when": booking.start_at.astimezone(tz).strftime("%d.%m.%Y %H:%M"),
                "amount": format_money(booking.prepay_due, salon.currency),
                "minutes": salon.prepay_timeout_min,
                "salon": salon.name,
                "buttons": [[_pay_button(client.language, booking.id)]],
            },
        )
    )
