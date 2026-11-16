"""Gift certificates (money on a code) and subscriptions (N visits for a fixed price)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, money, str_enum, uuid_pk
from app.models.enums import PaymentMethod


class GiftCertificate(Base):
    __tablename__ = "gift_certificates"
    __table_args__ = (
        UniqueConstraint("branch_id", "code", name="uq_gift_certificates_code"),
        CheckConstraint("amount > 0 AND balance >= 0 AND balance <= amount", name="balance"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(32))
    amount: Mapped[int] = money(default=None)
    balance: Mapped[int] = money(default=None)
    buyer_name: Mapped[str | None] = mapped_column(String(200))
    recipient_name: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text)
    expires_on: Mapped[date | None] = mapped_column(Date)
    payment_method: Mapped[PaymentMethod] = mapped_column(str_enum(PaymentMethod, "payment_method"))
    sold_at: Mapped[datetime] = mapped_column(server_default=func.now())
    sold_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    cancelled_at: Mapped[datetime | None] = mapped_column()


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    id: Mapped[uuid.UUID] = uuid_pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    # services a visit may include; empty = any service
    service_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), default=list, server_default=text("'{}'")
    )
    visits: Mapped[int] = mapped_column(Integer)
    price: Mapped[int] = money(default=None)
    valid_days: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "visits BETWEEN 1 AND 100 AND valid_days BETWEEN 1 AND 1000", name="limits"
        ),
    )


class ClientSubscription(Base):
    __tablename__ = "client_subscriptions"
    __table_args__ = (
        CheckConstraint("visits_left BETWEEN 0 AND visits_total", name="visits"),
        Index("ix_client_subscriptions_client", "client_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"))
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subscription_plans.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(200))  # snapshot of the plan
    service_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), default=list, server_default=text("'{}'")
    )
    visits_total: Mapped[int] = mapped_column(Integer)
    visits_left: Mapped[int] = mapped_column(Integer)
    price: Mapped[int] = money(default=None)
    payment_method: Mapped[PaymentMethod] = mapped_column(str_enum(PaymentMethod, "payment_method"))
    expires_on: Mapped[date] = mapped_column(Date)
    sold_at: Mapped[datetime] = mapped_column(server_default=func.now())
    sold_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    cancelled_at: Mapped[datetime | None] = mapped_column()


class VoucherUse(Base):
    """A certificate amount or a subscription visit applied to a booking (undoable)."""

    __tablename__ = "voucher_uses"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="amount"),
        CheckConstraint("(certificate_id IS NULL) <> (subscription_id IS NULL)", name="one_source"),
        Index("ix_voucher_uses_booking", "booking_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"))
    certificate_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gift_certificates.id", ondelete="CASCADE")
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("client_subscriptions.id", ondelete="CASCADE")
    )
    amount: Mapped[int] = money(default=None)  # how much of the bill it covered
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL")
    )
