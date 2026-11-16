"""Gift certificates and subscriptions.

Both are sold for money up front (the sale is the revenue) and later cover part of a booking's
bill. Applying one to a booking writes a VoucherUse and raises `bookings.voucher_amount`; at
completion the money the client still pays defaults to `total_due - voucher_amount`. A use can
be undone while the booking is open (balance / visit returned).
"""

from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.models import (
    Booking,
    Client,
    ClientSubscription,
    GiftCertificate,
    SubscriptionPlan,
    VoucherUse,
)
from app.models.enums import BookingKind, BookingStatus, PaymentMethod
from app.services.audit import Actor, AuditService

OPEN = (BookingStatus.PENDING, BookingStatus.CONFIRMED)
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I


def new_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    return f"GIFT-{raw[:4]}-{raw[4:]}"


def normalize_code(code: str) -> str:
    return code.strip().upper().replace(" ", "")


def certificate_state(cert: GiftCertificate, today: date) -> str:
    if cert.cancelled_at is not None:
        return "cancelled"
    if cert.balance == 0:
        return "used"
    if cert.expires_on is not None and cert.expires_on < today:
        return "expired"
    return "active"


def subscription_state(sub: ClientSubscription, today: date) -> str:
    if sub.cancelled_at is not None:
        return "cancelled"
    if sub.visits_left == 0:
        return "used"
    if sub.expires_on < today:
        return "expired"
    return "active"


class VoucherService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    # ---------------------------------------------------------------- certificates

    async def sell_certificate(
        self,
        branch_id: uuid.UUID,
        *,
        amount: int,
        expires_on: date | None,
        buyer_name: str | None,
        recipient_name: str | None,
        note: str | None,
        payment_method: PaymentMethod,
        actor: Actor,
    ) -> GiftCertificate:
        for _ in range(5):
            code = new_code()
            taken = await self.session.scalar(
                select(GiftCertificate.id).where(
                    GiftCertificate.branch_id == branch_id, GiftCertificate.code == code
                )
            )
            if taken is None:
                break
        cert = GiftCertificate(
            branch_id=branch_id,
            code=code,
            amount=amount,
            balance=amount,
            expires_on=expires_on,
            buyer_name=(buyer_name or "").strip() or None,
            recipient_name=(recipient_name or "").strip() or None,
            note=(note or "").strip() or None,
            payment_method=payment_method,
            sold_by=actor.id,
        )
        self.session.add(cert)
        await self.session.flush()
        self.audit.record(
            actor,
            "certificate.sell",
            "certificate",
            cert.id,
            after={"amount": amount, "code": code},
        )
        await self.session.commit()
        return cert

    async def certificates(self, branch_id: uuid.UUID, limit: int) -> list[GiftCertificate]:
        rows = await self.session.scalars(
            select(GiftCertificate)
            .where(GiftCertificate.branch_id == branch_id)
            .order_by(GiftCertificate.sold_at.desc())
            .limit(limit)
        )
        return list(rows)

    async def find_certificate(self, branch_id: uuid.UUID, code: str) -> GiftCertificate:
        cert = await self.session.scalar(
            select(GiftCertificate).where(
                GiftCertificate.branch_id == branch_id,
                GiftCertificate.code == normalize_code(code),
            )
        )
        if cert is None:
            raise NotFoundError("Certificate not found", code="certificate_not_found")
        return cert

    async def cancel_certificate(
        self, branch_id: uuid.UUID, cert_id: uuid.UUID, actor: Actor, now: datetime
    ) -> GiftCertificate:
        cert = await self.session.get(GiftCertificate, cert_id)
        if cert is None or cert.branch_id != branch_id:
            raise NotFoundError("Certificate not found")
        if cert.cancelled_at is None:
            cert.cancelled_at = now
            self.audit.record(actor, "certificate.cancel", "certificate", cert.id)
            await self.session.commit()
        return cert

    # ---------------------------------------------------------------- subscriptions

    async def plans(self, branch_id: uuid.UUID) -> list[SubscriptionPlan]:
        rows = await self.session.scalars(
            select(SubscriptionPlan)
            .where(SubscriptionPlan.branch_id == branch_id)
            .order_by(SubscriptionPlan.is_active.desc(), SubscriptionPlan.created_at)
        )
        return list(rows)

    async def plan(self, branch_id: uuid.UUID, plan_id: uuid.UUID) -> SubscriptionPlan:
        plan = await self.session.get(SubscriptionPlan, plan_id)
        if plan is None or plan.branch_id != branch_id:
            raise NotFoundError("Plan not found")
        return plan

    async def sell_subscription(
        self,
        branch_id: uuid.UUID,
        *,
        client_id: uuid.UUID,
        plan_id: uuid.UUID,
        payment_method: PaymentMethod,
        actor: Actor,
        today: date,
    ) -> ClientSubscription:
        plan = await self.plan(branch_id, plan_id)
        if not plan.is_active:
            raise ValidationAppError("The plan is archived", code="plan_inactive")
        client = await self.session.get(Client, client_id)
        if client is None or client.branch_id != branch_id:
            raise NotFoundError("Client not found")
        sub = ClientSubscription(
            branch_id=branch_id,
            client_id=client.id,
            plan_id=plan.id,
            name=plan.name,
            service_ids=list(plan.service_ids or []),
            visits_total=plan.visits,
            visits_left=plan.visits,
            price=plan.price,
            payment_method=payment_method,
            expires_on=today + timedelta(days=plan.valid_days),
            sold_by=actor.id,
        )
        self.session.add(sub)
        await self.session.flush()
        self.audit.record(
            actor,
            "subscription.sell",
            "client",
            client.id,
            after={"plan": plan.name, "price": plan.price, "subscription_id": str(sub.id)},
        )
        await self.session.commit()
        return sub

    async def client_subscriptions(
        self, branch_id: uuid.UUID, client_id: uuid.UUID | None, limit: int = 100
    ) -> list[tuple[ClientSubscription, str]]:
        query = (
            select(ClientSubscription, Client.name)
            .join(Client, Client.id == ClientSubscription.client_id)
            .where(ClientSubscription.branch_id == branch_id)
            .order_by(ClientSubscription.sold_at.desc())
            .limit(limit)
        )
        if client_id is not None:
            query = query.where(ClientSubscription.client_id == client_id)
        return [(sub, name) for sub, name in (await self.session.execute(query)).all()]

    async def cancel_subscription(
        self, branch_id: uuid.UUID, sub_id: uuid.UUID, actor: Actor, now: datetime
    ) -> ClientSubscription:
        sub = await self.session.get(ClientSubscription, sub_id)
        if sub is None or sub.branch_id != branch_id:
            raise NotFoundError("Subscription not found")
        if sub.cancelled_at is None:
            sub.cancelled_at = now
            self.audit.record(actor, "subscription.cancel", "client", sub.client_id)
            await self.session.commit()
        return sub

    # ---------------------------------------------------------------- applying to bookings

    async def _open_booking(self, branch_id: uuid.UUID, booking_id: uuid.UUID) -> Booking:
        booking = await self.session.scalar(
            select(Booking)
            .options(selectinload(Booking.services))
            .where(Booking.id == booking_id, Booking.branch_id == branch_id)
            .with_for_update(of=Booking)
        )
        if booking is None or booking.kind is not BookingKind.APPOINTMENT:
            raise NotFoundError("Booking not found")
        if booking.status not in OPEN:
            raise ConflictError("The booking is closed", code="booking_closed")
        return booking

    async def uses(self, branch_id: uuid.UUID, booking_id: uuid.UUID) -> list[VoucherUse]:
        rows = await self.session.scalars(
            select(VoucherUse)
            .join(Booking, Booking.id == VoucherUse.booking_id)
            .where(VoucherUse.booking_id == booking_id, Booking.branch_id == branch_id)
            .order_by(VoucherUse.created_at)
        )
        return list(rows)

    async def apply_certificate(
        self,
        branch_id: uuid.UUID,
        booking_id: uuid.UUID,
        *,
        code: str,
        amount: int | None,
        actor: Actor,
        today: date,
    ) -> VoucherUse:
        booking = await self._open_booking(branch_id, booking_id)
        cert = await self.find_certificate(branch_id, code)
        cert = await self.session.get(GiftCertificate, cert.id, with_for_update=True) or cert
        state = certificate_state(cert, today)
        if state != "active":
            raise ValidationAppError(f"The certificate is {state}", code=f"certificate_{state}")
        left_to_cover = booking.total_due - booking.voucher_amount
        if left_to_cover <= 0:
            raise ValidationAppError("Nothing left to pay", code="nothing_to_cover")
        use_amount = min(amount or cert.balance, cert.balance, left_to_cover)
        if use_amount <= 0:
            raise ValidationAppError("Check the amount", code="bad_amount")
        cert.balance -= use_amount
        booking.voucher_amount += use_amount
        booking.version += 1
        use = VoucherUse(
            booking_id=booking.id,
            certificate_id=cert.id,
            amount=use_amount,
            created_by=actor.id,
        )
        self.session.add(use)
        await self.session.flush()
        self.audit.record(
            actor,
            "certificate.apply",
            "booking",
            booking.id,
            after={"code": cert.code, "amount": use_amount, "balance": cert.balance},
        )
        await self.session.commit()
        return use

    async def apply_subscription(
        self,
        branch_id: uuid.UUID,
        booking_id: uuid.UUID,
        *,
        subscription_id: uuid.UUID,
        actor: Actor,
        today: date,
    ) -> VoucherUse:
        booking = await self._open_booking(branch_id, booking_id)
        sub = await self.session.get(ClientSubscription, subscription_id, with_for_update=True)
        if sub is None or sub.branch_id != branch_id or sub.client_id != booking.client_id:
            raise NotFoundError("Subscription not found")
        state = subscription_state(sub, today)
        if state != "active":
            raise ValidationAppError(f"The subscription is {state}", code=f"subscription_{state}")
        already = await self.session.scalar(
            select(VoucherUse.id).where(
                VoucherUse.booking_id == booking.id, VoucherUse.subscription_id.is_not(None)
            )
        )
        if already is not None:
            raise ConflictError("A subscription is already applied", code="subscription_applied")
        allowed = set(sub.service_ids or [])
        lines = [line for line in booking.services if not allowed or line.service_id in allowed]
        if not lines:
            raise ValidationAppError(
                "The subscription doesn't cover these services", code="subscription_services"
            )
        # cover the subscribed services' price, never more than what is left to pay
        covered = min(sum(line.price for line in lines), booking.total_due - booking.voucher_amount)
        sub.visits_left -= 1
        booking.voucher_amount += max(0, covered)
        booking.version += 1
        use = VoucherUse(
            booking_id=booking.id,
            subscription_id=sub.id,
            amount=max(0, covered),
            created_by=actor.id,
        )
        self.session.add(use)
        await self.session.flush()
        self.audit.record(
            actor,
            "subscription.apply",
            "booking",
            booking.id,
            after={"subscription": sub.name, "visits_left": sub.visits_left, "amount": covered},
        )
        await self.session.commit()
        return use

    async def undo(self, branch_id: uuid.UUID, use_id: uuid.UUID, actor: Actor) -> None:
        use = await self.session.get(VoucherUse, use_id)
        if use is None:
            raise NotFoundError("Not found")
        booking = await self._open_booking(branch_id, use.booking_id)
        if use.certificate_id is not None:
            cert = await self.session.get(GiftCertificate, use.certificate_id, with_for_update=True)
            if cert is not None:
                cert.balance = min(cert.amount, cert.balance + use.amount)
        if use.subscription_id is not None:
            sub = await self.session.get(
                ClientSubscription, use.subscription_id, with_for_update=True
            )
            if sub is not None:
                sub.visits_left = min(sub.visits_total, sub.visits_left + 1)
        booking.voucher_amount = max(0, booking.voucher_amount - use.amount)
        booking.version += 1
        self.audit.record(
            actor, "voucher.undo", "booking", booking.id, before={"amount": use.amount}
        )
        await self.session.delete(use)
        await self.session.commit()

    async def release_for_booking(self, booking: Booking) -> None:
        """A cancelled / no-show booking gives certificate money and visits back."""
        uses = await self.session.scalars(
            select(VoucherUse).where(VoucherUse.booking_id == booking.id)
        )
        for use in uses:
            if use.certificate_id is not None:
                cert = await self.session.get(GiftCertificate, use.certificate_id)
                if cert is not None:
                    cert.balance = min(cert.amount, cert.balance + use.amount)
            if use.subscription_id is not None:
                sub = await self.session.get(ClientSubscription, use.subscription_id)
                if sub is not None:
                    sub.visits_left = min(sub.visits_total, sub.visits_left + 1)
            await self.session.delete(use)
        booking.voucher_amount = 0
        await self.session.flush()
