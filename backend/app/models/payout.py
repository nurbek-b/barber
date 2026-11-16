from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, money, str_enum, uuid_pk
from app.models.enums import PaymentMethod


class BarberPayout(Base):
    """Money the salon paid a barber. Balance = barber's share of completed visits - payouts."""

    __tablename__ = "barber_payouts"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        Index("ix_barber_payouts_barber", "barber_id", "paid_on"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"))
    barber_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("barbers.id", ondelete="CASCADE"))
    amount: Mapped[int] = money(default=None)
    paid_on: Mapped[date] = mapped_column(Date)
    method: Mapped[PaymentMethod] = mapped_column(str_enum(PaymentMethod, "payment_method"))
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
