"""Loyalty program rules on top of the ledger."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationAppError
from app.domain import bonus as rules
from app.domain.pricing import percent_of
from app.models import (
    BonusLotConsumption,
    BonusSettings,
    BonusTransaction,
    Booking,
    Client,
    LoyaltyLevel,
    SalonSettings,
    TelegramOutbox,
    User,
)
from app.models.enums import BonusTxType, BookingKind, BookingStatus
from app.notify.templates import format_money
from app.services.audit import Actor, AuditService
from app.services.bonus_ledger import BonusLedger, NotEnoughBonusesError

logger = structlog.get_logger(__name__)

CREDIT_REASON = {
    BonusTxType.WELCOME: {
        "ru": "Приветственный бонус",
        "ky": "Куттуктоо бонусу",
        "en": "Welcome bonus",
    },
    BonusTxType.BIRTHDAY: {
        "ru": "С днём рождения",
        "ky": "Туулган күнүңүз менен",
        "en": "Happy birthday",
    },
    BonusTxType.REFERRAL: {
        "ru": "Бонус за приглашение",
        "ky": "Чакыруу бонусу",
        "en": "Referral bonus",
    },
    BonusTxType.MANUAL: {
        "ru": "Начисление от салона",
        "ky": "Салондон бонус",
        "en": "Bonus from the salon",
    },
}


def to_domain_level(level: LoyaltyLevel) -> rules.Level:
    return rules.Level(
        id=level.id,
        min_visits=level.min_visits,
        min_spent=level.min_spent,
        cashback_bp=level.cashback_bp,
        sort_order=level.sort_order,
    )


@dataclass(frozen=True, slots=True)
class BonusSummary:
    enabled: bool
    balance: int
    level: LoyaltyLevel | None
    next_level: LoyaltyLevel | None
    visits_left: int
    spent_left: int
    cashback_bp: int
    max_spend_bp: int
    expiring: list[tuple[int, datetime]]


class BonusService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.ledger = BonusLedger(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ settings

    async def settings(self, branch_id: uuid.UUID) -> BonusSettings:
        settings = await self.session.get(BonusSettings, branch_id)
        if settings is None:
            settings = BonusSettings(branch_id=branch_id, enabled=False)
            self.session.add(settings)
            await self.session.flush()
        return settings

    async def levels(self, branch_id: uuid.UUID) -> list[LoyaltyLevel]:
        rows = await self.session.execute(
            select(LoyaltyLevel)
            .where(LoyaltyLevel.branch_id == branch_id)
            .order_by(LoyaltyLevel.sort_order, LoyaltyLevel.min_spent)
        )
        return list(rows.scalars())

    # ------------------------------------------------------------------ notify

    async def _notify(
        self, client: Client, template: str, values: dict[str, object], dedupe: str | None = None
    ) -> None:
        if client.user_id is None:
            return
        user = await self.session.get(User, client.user_id)
        if user is None or user.bot_blocked:
            return
        if dedupe is not None:
            exists = await self.session.scalar(
                select(TelegramOutbox.id).where(TelegramOutbox.dedupe_key == dedupe)
            )
            if exists is not None:
                return
        self.session.add(
            TelegramOutbox(
                chat_id=user.telegram_id,
                template_key=template,
                language=client.language,
                payload=values,
                dedupe_key=dedupe,
            )
        )

    async def _currency(self, branch_id: uuid.UUID) -> str:
        salon = await self.session.get(SalonSettings, branch_id)
        return salon.currency if salon else "KGS"

    async def _notify_credit(
        self, client: Client, tx: BonusTransaction, reason_type: BonusTxType
    ) -> None:
        currency = await self._currency(client.branch_id)
        reason = CREDIT_REASON.get(reason_type, CREDIT_REASON[BonusTxType.MANUAL])
        await self._notify(
            client,
            "bonus_credited_client",
            {
                "reason": reason.get(client.language) or reason["ru"],
                "amount": format_money(tx.amount, currency),
                "balance": format_money(tx.balance_after, currency),
            },
        )

    # ------------------------------------------------------------------ bookings

    async def spend_for_booking(self, booking: Booking, amount: int, now: datetime) -> None:
        if amount <= 0 or booking.client_id is None:
            return
        settings = await self.settings(booking.branch_id)
        if not settings.enabled:
            raise ValidationAppError("Bonuses are disabled", code="bonus_disabled")
        client = await self.ledger.lock_client(booking.client_id)
        limit = percent_of(booking.subtotal, settings.max_spend_bp)
        if amount > limit:
            raise ValidationAppError(
                "Too many bonuses for this booking",
                code="bonus_limit",
                details={"max_bonus_spend": min(limit, client.bonus_balance)},
            )
        await self.ledger.debit(client, BonusTxType.SPEND, amount, now, booking_id=booking.id)

    async def refund_for_booking(
        self, booking: Booking, now: datetime, amount: int | None = None
    ) -> int:
        """Cancelled / no-show bookings get spent bonuses back (all or `amount`)."""
        if booking.client_id is None:
            return 0
        client = await self.ledger.lock_client(booking.client_id)
        return await self.ledger.refund_booking(client, booking.id, now, amount)

    async def on_completed(self, booking: Booking, now: datetime) -> int:
        """Visit counters, level, cashback and referral rewards. Idempotent per booking."""
        if booking.client_id is None or booking.kind is not BookingKind.APPOINTMENT:
            return 0
        if booking.status is not BookingStatus.COMPLETED:
            raise ValueError("booking is not completed")
        settings = await self.settings(booking.branch_id)
        client = await self.ledger.lock_client(booking.client_id)
        paid = booking.paid_amount if booking.paid_amount is not None else booking.total_due

        # Called exactly once per booking: the transition to `completed` is one-way and
        # guarded by the booking's optimistic version. The earn row also has a dedupe key.
        client.visits_count += 1
        client.total_spent += max(paid, 0)

        levels = await self.levels(booking.branch_id)
        domain_levels = [to_domain_level(level) for level in levels]
        resolved = rules.resolve_level(
            domain_levels,
            client.visits_count,
            client.total_spent,
            rules.LevelRule(settings.level_rule.value),
            client.level_id,
        )
        client.level_id = resolved.id if resolved else None

        earned = 0
        if settings.enabled:
            earned = rules.cashback(paid, resolved, settings.base_cashback_bp)
            tx = await self.ledger.credit(
                client,
                BonusTxType.EARN,
                earned,
                now,
                expires_at=rules.lot_expiry(now, settings.lifetime_days),
                booking_id=booking.id,
                dedupe_key=f"earn:booking:{booking.id}",
            )
            if tx is not None:
                currency = await self._currency(booking.branch_id)
                await self._notify(
                    client,
                    "bonus_earned_client",
                    {
                        "amount": format_money(tx.amount, currency),
                        "balance": format_money(tx.balance_after, currency),
                    },
                )
            else:
                earned = 0
            if client.visits_count == 1:
                await self._referral_rewards(client, settings, now)
        await self.session.flush()
        return earned

    async def _referral_rewards(
        self, client: Client, settings: BonusSettings, now: datetime
    ) -> None:
        if not settings.referral_enabled or client.referred_by_client_id is None:
            return
        expires = rules.lot_expiry(now, settings.lifetime_days)
        referee_tx = await self.ledger.credit(
            client,
            BonusTxType.REFERRAL,
            settings.referee_amount,
            now,
            expires_at=expires,
            dedupe_key=f"referral:referee:{client.id}",
        )
        if referee_tx is not None:
            await self._notify_credit(client, referee_tx, BonusTxType.REFERRAL)
        referrer = await self.ledger.lock_client(client.referred_by_client_id)
        referrer_tx = await self.ledger.credit(
            referrer,
            BonusTxType.REFERRAL,
            settings.referrer_amount,
            now,
            expires_at=expires,
            dedupe_key=f"referral:referrer:{client.id}",
        )
        if referrer_tx is not None:
            await self._notify_credit(referrer, referrer_tx, BonusTxType.REFERRAL)

    # ------------------------------------------------------------------ one-off credits

    async def welcome(self, client_id: uuid.UUID, now: datetime) -> int:
        client = await self.ledger.lock_client(client_id)
        settings = await self.settings(client.branch_id)
        if not (settings.enabled and settings.welcome_enabled):
            return 0
        tx = await self.ledger.credit(
            client,
            BonusTxType.WELCOME,
            settings.welcome_amount,
            now,
            expires_at=rules.lot_expiry(now, settings.lifetime_days),
            dedupe_key=f"welcome:{client.id}",
        )
        if tx is None:
            return 0
        await self._notify_credit(client, tx, BonusTxType.WELCOME)
        return tx.amount

    async def adjust(
        self,
        client_id: uuid.UUID,
        amount: int,
        comment: str,
        actor: Actor,
        now: datetime,
        expires_in_days: int | None,
    ) -> BonusTransaction:
        """Manual credit (amount > 0) or debit (amount < 0) by staff. Comment is mandatory."""
        comment = comment.strip()
        if not comment:
            raise ValidationAppError("A comment is required", code="comment_required")
        if amount == 0:
            raise ValidationAppError("Amount must not be zero", code="zero_amount")
        client = await self.ledger.lock_client(client_id)
        before = client.bonus_balance
        if amount > 0:
            settings = await self.settings(client.branch_id)
            days = expires_in_days if expires_in_days is not None else settings.lifetime_days
            tx = await self.ledger.credit(
                client,
                BonusTxType.MANUAL,
                amount,
                now,
                expires_at=rules.lot_expiry(now, days),
                comment=comment,
                admin_id=actor.id,
            )
            if tx is None:  # pragma: no cover - credit without dedupe key always writes
                raise RuntimeError("manual credit was not written")
            await self._notify_credit(client, tx, BonusTxType.MANUAL)
        else:
            tx = await self.ledger.debit(
                client, BonusTxType.MANUAL, -amount, now, comment=comment, admin_id=actor.id
            )
        self.audit.record(
            actor,
            "bonus.adjust",
            "client",
            client.id,
            before={"balance": before},
            after={"balance": client.bonus_balance, "amount": amount, "comment": comment},
        )
        return tx

    # ------------------------------------------------------------------ jobs

    async def expire_due(self, now: datetime) -> int:
        """Burn expired remainders. One EXPIRE transaction per client."""
        consumed = func.coalesce(
            select(func.sum(BonusLotConsumption.amount))
            .where(BonusLotConsumption.lot_tx_id == BonusTransaction.id)
            .correlate(BonusTransaction)
            .scalar_subquery(),
            0,
        )
        client_ids = list(
            (
                await self.session.execute(
                    select(BonusTransaction.client_id)
                    .where(
                        BonusTransaction.amount > 0,
                        BonusTransaction.expires_at <= now,
                        BonusTransaction.amount - consumed > 0,
                    )
                    .distinct()
                )
            ).scalars()
        )
        burned = 0
        for client_id in client_ids:
            client = await self.ledger.lock_client(client_id)
            lots = rules.expired_lots(await self.ledger.lots(client_id), now)
            total = sum(lot.remaining for lot in lots)
            if total <= 0:
                continue
            await self.ledger.debit(
                client,
                BonusTxType.EXPIRE,
                total,
                now,
                allocations=[rules.Allocation(lot.tx_id, lot.remaining) for lot in lots],
            )
            burned += total
        return burned

    async def warn_expiring(self, now: datetime) -> int:
        """Tell clients about bonuses expiring within `expiry_warning_days` (once per day)."""
        sent = 0
        for settings in (await self.session.execute(select(BonusSettings))).scalars().all():
            if not settings.enabled or settings.expiry_warning_days <= 0:
                continue
            salon = await self.session.get(SalonSettings, settings.branch_id)
            if salon is None:
                continue
            tz = ZoneInfo(salon.timezone)
            horizon = now + timedelta(days=settings.expiry_warning_days)
            clients = (
                (
                    await self.session.execute(
                        select(Client).where(
                            Client.branch_id == settings.branch_id,
                            Client.bonus_balance > 0,
                            Client.user_id.is_not(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for client in clients:
                lots = [
                    lot
                    for lot in await self.ledger.lots(client.id)
                    if lot.expires_at is not None and now < lot.expires_at <= horizon
                ]
                if not lots:
                    continue
                first = min(lot.expires_at for lot in lots if lot.expires_at)
                amount = sum(lot.remaining for lot in lots)
                day = now.astimezone(tz).date().isoformat()
                await self._notify(
                    client,
                    "bonus_expiring_client",
                    {
                        "amount": format_money(amount, salon.currency),
                        "date": first.astimezone(tz).strftime("%d.%m.%Y"),
                    },
                    dedupe=f"bonus_expiring:{client.id}:{day}",
                )
                sent += 1
        return sent

    async def birthdays(self, now: datetime) -> int:
        credited = 0
        for settings in (await self.session.execute(select(BonusSettings))).scalars().all():
            if not (settings.enabled and settings.birthday_enabled and settings.birthday_amount):
                continue
            salon = await self.session.get(SalonSettings, settings.branch_id)
            if salon is None:
                continue
            today = now.astimezone(ZoneInfo(salon.timezone)).date()
            target = today + timedelta(days=settings.birthday_days_before)
            months = {target.month}
            if target.month == 2 and target.day == 28:
                months.add(2)  # Feb 29 birthdays in non-leap years
            candidates = (
                (
                    await self.session.execute(
                        select(Client.id).where(
                            Client.branch_id == settings.branch_id,
                            Client.birthday.is_not(None),
                            Client.is_blocked.is_(False),
                            extract("month", Client.birthday).in_(months),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for client_id in candidates:
                client = await self.ledger.lock_client(client_id)
                if client.birthday is None:
                    continue
                year = rules.birthday_due(client.birthday, today, settings.birthday_days_before)
                if year is None:
                    continue
                tx = await self.ledger.credit(
                    client,
                    BonusTxType.BIRTHDAY,
                    settings.birthday_amount,
                    now,
                    expires_at=rules.lot_expiry(now, settings.lifetime_days),
                    dedupe_key=f"birthday:{client.id}:{year}",
                )
                if tx is not None:
                    await self._notify_credit(client, tx, BonusTxType.BIRTHDAY)
                    credited += 1
        return credited

    # ------------------------------------------------------------------ read

    async def history(
        self,
        client_id: uuid.UUID,
        limit: int,
        after: tuple[datetime, uuid.UUID] | None = None,
    ) -> list[BonusTransaction]:
        query = select(BonusTransaction).where(BonusTransaction.client_id == client_id)
        if after is not None:
            query = query.where(
                (BonusTransaction.created_at < after[0])
                | ((BonusTransaction.created_at == after[0]) & (BonusTransaction.id < after[1]))
            )
        rows = await self.session.execute(
            query.order_by(BonusTransaction.created_at.desc(), BonusTransaction.id.desc()).limit(
                limit
            )
        )
        return list(rows.scalars())

    async def referral_stats(self, client: Client) -> tuple[int, int]:
        invited = await self.session.scalar(
            select(func.count())
            .select_from(Client)
            .where(Client.referred_by_client_id == client.id)
        )
        rewarded = await self.session.scalar(
            select(func.count())
            .select_from(BonusTransaction)
            .where(
                BonusTransaction.client_id == client.id,
                BonusTransaction.type == BonusTxType.REFERRAL,
                BonusTransaction.dedupe_key.like("referral:referrer:%"),
            )
        )
        return int(invited or 0), int(rewarded or 0)

    async def summary(self, client: Client, now: datetime) -> BonusSummary:
        settings = await self.settings(client.branch_id)
        levels = await self.levels(client.branch_id)
        by_id = {level.id: level for level in levels}
        current = by_id.get(client.level_id) if client.level_id else None
        progress = rules.progress_to_next(
            [to_domain_level(level) for level in levels],
            to_domain_level(current) if current else None,
            client.visits_count,
            client.total_spent,
            rules.LevelRule(settings.level_rule.value),
        )
        horizon = now + timedelta(days=max(settings.expiry_warning_days, 30))
        expiring = sorted(
            (lot.remaining, lot.expires_at)
            for lot in await self.ledger.lots(client.id)
            if lot.expires_at is not None and now < lot.expires_at <= horizon
        )
        return BonusSummary(
            enabled=settings.enabled,
            balance=client.bonus_balance,
            level=current,
            next_level=by_id.get(progress.next_level.id) if progress.next_level else None,
            visits_left=progress.visits_left,
            spent_left=progress.spent_left,
            cashback_bp=current.cashback_bp if current else settings.base_cashback_bp,
            max_spend_bp=settings.max_spend_bp,
            expiring=[(amount, when) for amount, when in expiring],
        )


__all__ = ["BonusService", "BonusSummary", "NotEnoughBonusesError"]
