from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, ForeignKey, Index, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk


class WaitlistEntry(Base):
    """'Tell me if a slot frees up' for a fully booked day (one barber, or any barber)."""

    __tablename__ = "waitlist_entries"
    __table_args__ = (
        Index(
            "ix_waitlist_pending",
            "branch_id",
            "day",
            postgresql_where=text("notified_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"))
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), index=True
    )
    # NULL = any barber
    barber_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("barbers.id", ondelete="CASCADE")
    )
    day: Mapped[date] = mapped_column(Date)
    service_ids: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    notified_at: Mapped[datetime | None] = mapped_column()
