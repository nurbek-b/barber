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
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, money, str_enum, uuid_pk
from app.models.enums import PromoKind


class PromoCode(Base):
    """A discount code entered in the Mini App. Uses are counted from active/completed
    bookings that carry it, so a cancelled booking gives the use back."""

    __tablename__ = "promo_codes"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'percent' AND value BETWEEN 1 AND 10000) OR (kind = 'fixed' AND value > 0)",
            name="value",
        ),
        CheckConstraint("max_uses IS NULL OR max_uses > 0", name="max_uses"),
        CheckConstraint("max_uses_per_client > 0", name="per_client"),
        Index("ux_promo_codes_branch_code", "branch_id", text("upper(code)"), unique=True),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(32))
    kind: Mapped[PromoKind] = mapped_column(str_enum(PromoKind, "promo_kind"))
    # percent: basis points (2000 = 20 %); fixed: tyiyn
    value: Mapped[int] = mapped_column(Integer)
    max_discount: Mapped[int | None] = money(nullable=True, default=None)  # cap for percent
    min_subtotal: Mapped[int] = money()
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    max_uses: Mapped[int | None] = mapped_column(Integer)
    max_uses_per_client: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    first_visit_only: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    description: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
