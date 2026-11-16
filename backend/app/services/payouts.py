"""Barber payouts ledger.

A barber earns `master_share(subtotal, commission)` of every completed visit (the rate fixed at
completion; older visits use the current rate — the same rule as the finance report). The salon
records each payout; the balance owed is everything earned minus everything paid out. Wrong
entries are deleted (audited) rather than edited, so the history stays simple.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.domain.slots import local_day_bounds
from app.models import Barber, BarberPayout, Booking, TelegramOutbox
from app.models.enums import BookingKind, BookingStatus, PaymentMethod
from app.notify.templates import format_money
from app.services.audit import Actor, AuditService
from app.services.branches import BranchService


@dataclass(frozen=True, slots=True)
class Balance:
    barber: Barber
    earned: int
    paid: int
    last_paid_on: date | None

    @property
    def due(self) -> int:
        return self.earned - self.paid


class PayoutService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def balances(self, branch_id: uuid.UUID, until: date) -> list[Balance]:
        """Earned (completed visits up to the end of `until`) vs paid, for every barber."""
        salon = await BranchService(self.session).settings(branch_id)
        end = local_day_bounds(until, ZoneInfo(salon.timezone)).end
        rate = func.coalesce(Booking.barber_commission_bp, Barber.commission_bp)
        earned_rows = await self.session.execute(
            select(Booking.barber_id, func.sum(func.div(Booking.subtotal * rate + 5_000, 10_000)))
            .join(Barber, Barber.id == Booking.barber_id)
            .where(
                Booking.branch_id == branch_id,
                Booking.kind == BookingKind.APPOINTMENT,
                Booking.status == BookingStatus.COMPLETED,
                Booking.start_at < end,
            )
            .group_by(Booking.barber_id)
        )
        earned = {barber_id: int(total or 0) for barber_id, total in earned_rows.all()}
        paid_rows = await self.session.execute(
            select(
                BarberPayout.barber_id,
                func.sum(BarberPayout.amount),
                func.max(BarberPayout.paid_on),
            )
            .where(BarberPayout.branch_id == branch_id, BarberPayout.paid_on <= until)
            .group_by(BarberPayout.barber_id)
        )
        paid = {barber_id: (int(total), last) for barber_id, total, last in paid_rows.all()}
        barbers = await self.session.scalars(
            select(Barber)
            .where(Barber.branch_id == branch_id)
            .order_by(Barber.sort_order, Barber.name)
        )
        result = []
        for barber in barbers:
            total_paid, last = paid.get(barber.id, (0, None))
            got = earned.get(barber.id, 0)
            if not barber.is_active and got == total_paid == 0:
                continue
            result.append(Balance(barber, got, total_paid, last))
        return result

    async def history(
        self, branch_id: uuid.UUID, barber_id: uuid.UUID | None, limit: int
    ) -> list[tuple[BarberPayout, str]]:
        query = (
            select(BarberPayout, Barber.name)
            .join(Barber, Barber.id == BarberPayout.barber_id)
            .where(BarberPayout.branch_id == branch_id)
            .order_by(BarberPayout.paid_on.desc(), BarberPayout.created_at.desc())
            .limit(limit)
        )
        if barber_id:
            query = query.where(BarberPayout.barber_id == barber_id)
        return [(payout, name) for payout, name in (await self.session.execute(query)).all()]

    async def create(
        self,
        branch_id: uuid.UUID,
        *,
        barber_id: uuid.UUID,
        amount: int,
        paid_on: date,
        method: PaymentMethod,
        note: str | None,
        actor: Actor,
        now: datetime,
    ) -> tuple[BarberPayout, str]:
        barber = await self.session.get(Barber, barber_id)
        if barber is None or barber.branch_id != branch_id:
            raise NotFoundError("Barber not found")
        payout = BarberPayout(
            branch_id=branch_id,
            barber_id=barber.id,
            amount=amount,
            paid_on=paid_on,
            method=method,
            note=(note or "").strip() or None,
            created_by=actor.id,
        )
        self.session.add(payout)
        await self.session.flush()
        AuditService(self.session).record(
            actor,
            "payout.create",
            "barber",
            barber.id,
            after={"amount": amount, "paid_on": paid_on.isoformat(), "method": method.value},
        )
        if barber.telegram_chat_id:
            salon = await BranchService(self.session).settings(branch_id)
            self.session.add(
                TelegramOutbox(
                    chat_id=barber.telegram_chat_id,
                    template_key="payout_barber",
                    language=salon.default_language,
                    payload={
                        "amount": format_money(amount, salon.currency),
                        "date": paid_on.strftime("%d.%m.%Y"),
                        "note": payout.note or "",
                    },
                    dedupe_key=f"payout:{payout.id}",
                )
            )
        await self.session.commit()
        return payout, barber.name

    async def delete(self, branch_id: uuid.UUID, payout_id: uuid.UUID, actor: Actor) -> None:
        payout = await self.session.get(BarberPayout, payout_id)
        if payout is None or payout.branch_id != branch_id:
            raise NotFoundError("Payout not found")
        AuditService(self.session).record(
            actor,
            "payout.delete",
            "barber",
            payout.barber_id,
            before={"amount": payout.amount, "paid_on": payout.paid_on.isoformat()},
        )
        await self.session.delete(payout)
        await self.session.commit()
