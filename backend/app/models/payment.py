from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, money, str_enum, uuid_pk
from app.models.enums import PaymentMethod, PaymentStatus


class Payment(Base):
    """Money received for a booking before or apart from the visit (QR transfer, cash deposit).

    A client's "I paid" is a CLAIMED row until the salon checks its bank app and confirms it;
    only CONFIRMED rows count in `bookings.prepaid_amount`.
    """

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        Index("ix_payments_booking", "booking_id"),
        Index("ix_payments_branch_status", "branch_id", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"))
    booking_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE")
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    amount: Mapped[int] = money(default=None)
    method: Mapped[PaymentMethod] = mapped_column(str_enum(PaymentMethod, "payment_method"))
    status: Mapped[PaymentStatus] = mapped_column(str_enum(PaymentStatus, "payment_status"))
    by_client: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column()
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL")
    )
