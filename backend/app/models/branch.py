from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class Branch(TimestampMixin, Base):
    __tablename__ = "branches"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class SalonSettings(TimestampMixin, Base):
    __tablename__ = "salon_settings"
    __table_args__ = (
        CheckConstraint("slot_step_min BETWEEN 5 AND 120", name="slot_step"),
        CheckConstraint("buffer_min BETWEEN 0 AND 120", name="buffer"),
        CheckConstraint("min_lead_time_min >= 0", name="lead_time"),
        CheckConstraint("max_days_ahead BETWEEN 1 AND 365", name="days_ahead"),
        CheckConstraint("cancel_min_hours >= 0", name="cancel_hours"),
        CheckConstraint("reschedule_min_hours >= 0", name="reschedule_hours"),
        CheckConstraint("max_active_bookings_per_client >= 1", name="max_active"),
        CheckConstraint("revisit_after_days BETWEEN 0 AND 365", name="revisit_days"),
        CheckConstraint("prepay_percent BETWEEN 0 AND 100", name="prepay_percent"),
    )

    branch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("branches.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Bishkek")
    currency: Mapped[str] = mapped_column(String(3), default="KGS")
    default_language: Mapped[str] = mapped_column(String(5), default="ru")
    slot_step_min: Mapped[int] = mapped_column(SmallInteger, default=15)
    buffer_min: Mapped[int] = mapped_column(SmallInteger, default=0)
    min_lead_time_min: Mapped[int] = mapped_column(Integer, default=60)
    max_days_ahead: Mapped[int] = mapped_column(SmallInteger, default=30)
    cancel_min_hours: Mapped[int] = mapped_column(SmallInteger, default=2)
    reschedule_min_hours: Mapped[int] = mapped_column(SmallInteger, default=2)
    max_active_bookings_per_client: Mapped[int] = mapped_column(SmallInteger, default=3)
    reminder_offsets_min: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), default=lambda: [1440, 120], server_default=text("'{1440,120}'")
    )
    admin_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    notify_barbers: Mapped[bool] = mapped_column(Boolean, default=False)
    notification_templates: Mapped[dict[str, Any]] = mapped_column(
        default=dict, server_default=text("'{}'::jsonb")
    )
    contacts: Mapped[dict[str, Any]] = mapped_column(
        default=dict, server_default=text("'{}'::jsonb")
    )
    # map pages where happy clients are asked for a public review: {"2gis": url, "google": url}
    review_links: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    # payments: the salon's bank QR and a hint shown next to it (bank, recipient)
    payment_qr_url: Mapped[str | None] = mapped_column(String(512))
    payment_note: Mapped[str | None] = mapped_column(String(300))
    # prepayment for unreliable clients: % of the total (0 = off), required after N no-shows
    # or when the client is flagged; unpaid bookings are cancelled after prepay_timeout_min
    prepay_percent: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    prepay_after_no_shows: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    prepay_timeout_min: Mapped[int] = mapped_column(SmallInteger, default=120, server_default="120")
    # shop delivery (pickup is always available); fee in tyiyn, 0 = free
    delivery_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    delivery_fee: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    # days after a visit to remind the client to come again; 0 = off
    revisit_after_days: Mapped[int] = mapped_column(SmallInteger, default=30, server_default="30")
    # branding for the Mini App: /media/salon/... URLs
    logo_url: Mapped[str | None] = mapped_column(String(512))
    gallery: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
