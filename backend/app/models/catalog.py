from __future__ import annotations

import uuid
from datetime import date, time
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    Time,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, I18n, TimestampMixin, money, str_enum, uuid_pk
from app.models.enums import ScheduleExceptionKind


class Barber(TimestampMixin, Base):
    __tablename__ = "barbers"
    __table_args__ = (
        CheckConstraint("rating_x100 BETWEEN 0 AND 500", name="rating"),
        CheckConstraint("commission_bp BETWEEN 0 AND 10000", name="commission_bp"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    # master's share of the services price, basis points (4000 = 40 %); set by the owner
    commission_bp: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    photo_url: Mapped[str | None] = mapped_column(String(512))
    # works catalogue shown on the barber's Mini App profile: /media/portfolio/... URLs
    portfolio: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    specialization_i18n: Mapped[I18n] = mapped_column(
        default=dict, server_default=text("'{}'::jsonb")
    )
    bio_i18n: Mapped[I18n] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    rating_x100: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    rating_count: Mapped[int] = mapped_column(default=0, server_default="0")
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_bookable_online: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger)  # for barber notifications

    services: Mapped[list[BarberService]] = relationship(
        back_populates="barber", cascade="all, delete-orphan", lazy="raise"
    )


class BarberSchedule(Base):
    """Weekly template: one row per working interval. A break is a gap between rows.

    end_time <= start_time means the interval ends on the next day (overnight shift).
    Times are local to the salon timezone.
    """

    __tablename__ = "barber_schedules"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday"),
        CheckConstraint("start_time <> end_time", name="non_empty"),
        Index("ix_barber_schedules_barber_weekday", "barber_id", "weekday"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    barber_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("barbers.id", ondelete="CASCADE"))
    weekday: Mapped[int] = mapped_column(SmallInteger)  # 0 = Monday
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)


class BarberScheduleException(TimestampMixin, Base):
    __tablename__ = "barber_schedule_exceptions"
    __table_args__ = (
        CheckConstraint("date_to >= date_from", name="date_range"),
        Index("ix_barber_exceptions_barber_dates", "barber_id", "date_from", "date_to"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    barber_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("barbers.id", ondelete="CASCADE"))
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    kind: Mapped[ScheduleExceptionKind] = mapped_column(
        str_enum(ScheduleExceptionKind, "schedule_exception_kind")
    )
    # custom_hours: [{"start": "10:00", "end": "16:00"}]
    intervals: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    note: Mapped[str | None] = mapped_column(Text)


class ServiceCategory(TimestampMixin, Base):
    __tablename__ = "service_categories"

    id: Mapped[uuid.UUID] = uuid_pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), index=True)
    name_i18n: Mapped[I18n] = mapped_column()
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")


class Service(TimestampMixin, Base):
    __tablename__ = "services"
    __table_args__ = (
        CheckConstraint("duration_min BETWEEN 5 AND 600", name="duration"),
        CheckConstraint("base_price >= 0", name="price"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), index=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_categories.id", ondelete="SET NULL"), index=True
    )
    name_i18n: Mapped[I18n] = mapped_column()
    description_i18n: Mapped[I18n] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    duration_min: Mapped[int] = mapped_column(SmallInteger)
    base_price: Mapped[int] = money()
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")


class BarberService(Base):
    """Which services a barber performs, with optional price/duration overrides."""

    __tablename__ = "barber_services"
    __table_args__ = (
        CheckConstraint("price IS NULL OR price >= 0", name="price"),
        CheckConstraint("duration_min IS NULL OR duration_min BETWEEN 5 AND 600", name="duration"),
    )

    barber_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("barbers.id", ondelete="CASCADE"), primary_key=True
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("services.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    price: Mapped[int | None] = money(nullable=True, default=None)
    duration_min: Mapped[int | None] = mapped_column(SmallInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    barber: Mapped[Barber] = relationship(back_populates="services", lazy="raise")
    service: Mapped[Service] = relationship(lazy="raise")
