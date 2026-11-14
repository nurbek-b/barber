from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, I18n, TimestampMixin, money, str_enum, uuid_pk
from app.models.enums import BonusTxType, LevelRule


class BonusSettings(TimestampMixin, Base):
    """Percentages are basis points: 500 = 5%."""

    __tablename__ = "bonus_settings"
    __table_args__ = (
        CheckConstraint("base_cashback_bp BETWEEN 0 AND 10000", name="cashback"),
        CheckConstraint("max_spend_bp BETWEEN 0 AND 10000", name="max_spend"),
        CheckConstraint("lifetime_days IS NULL OR lifetime_days > 0", name="lifetime"),
    )

    branch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    base_cashback_bp: Mapped[int] = mapped_column(Integer, default=500)
    max_spend_bp: Mapped[int] = mapped_column(Integer, default=3000)
    lifetime_days: Mapped[int | None] = mapped_column(Integer, default=180)
    level_rule: Mapped[LevelRule] = mapped_column(
        str_enum(LevelRule, "level_rule"), default=LevelRule.ANY
    )
    welcome_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    welcome_amount: Mapped[int] = money()
    birthday_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    birthday_amount: Mapped[int] = money()
    birthday_days_before: Mapped[int] = mapped_column(SmallInteger, default=0)
    referral_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    referrer_amount: Mapped[int] = money()
    referee_amount: Mapped[int] = money()
    expiry_warning_days: Mapped[int] = mapped_column(SmallInteger, default=3)


class LoyaltyLevel(TimestampMixin, Base):
    """A level is reached by visits and/or total paid, combined by bonus_settings.level_rule."""

    __tablename__ = "loyalty_levels"
    __table_args__ = (
        CheckConstraint("min_visits >= 0 AND min_spent >= 0", name="thresholds"),
        CheckConstraint("cashback_bp BETWEEN 0 AND 10000", name="cashback"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), index=True)
    name_i18n: Mapped[I18n] = mapped_column()
    min_visits: Mapped[int] = mapped_column(Integer, default=0)
    min_spent: Mapped[int] = money()
    cashback_bp: Mapped[int] = mapped_column(Integer)
    color: Mapped[str | None] = mapped_column(String(16))
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0)


class BonusTransaction(Base):
    """Append-only ledger. Credits (amount > 0) are FIFO lots with an optional expires_at."""

    __tablename__ = "bonus_transactions"
    __table_args__ = (
        CheckConstraint("amount <> 0", name="non_zero"),
        CheckConstraint("balance_after >= 0", name="balance_non_negative"),
        CheckConstraint(
            "type <> 'manual' OR (comment IS NOT NULL AND length(comment) > 0)",
            name="manual_comment",
        ),
        Index("ix_bonus_tx_client_created", "client_id", "created_at"),
        Index(
            "ix_bonus_tx_lots",
            "client_id",
            "expires_at",
            postgresql_where=text("amount > 0"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id"))
    type: Mapped[BonusTxType] = mapped_column(str_enum(BonusTxType, "bonus_tx_type"))
    amount: Mapped[int] = mapped_column(BigInteger)
    balance_after: Mapped[int] = mapped_column(BigInteger)
    booking_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bookings.id", ondelete="SET NULL"), index=True
    )
    expires_at: Mapped[datetime | None] = mapped_column()
    comment: Mapped[str | None] = mapped_column(Text)
    created_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    dedupe_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class BonusLotConsumption(Base):
    """How much of a credit lot was consumed by a debit (spend/expire/manual-)."""

    __tablename__ = "bonus_lot_consumptions"
    __table_args__ = (CheckConstraint("amount > 0", name="positive"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    lot_tx_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bonus_transactions.id"), index=True)
    consumer_tx_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bonus_transactions.id"), index=True
    )
    amount: Mapped[int] = mapped_column(BigInteger)
