from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk


class FunnelEvent(Base):
    """One booking-funnel step reached in one anonymous app session (no personal data)."""

    __tablename__ = "funnel_events"
    __table_args__ = (
        UniqueConstraint("session_id", "step"),
        Index("ix_funnel_events_branch_created", "branch_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"))
    session_id: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16))  # miniapp | web
    step: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
