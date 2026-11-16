from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, I18n, TimestampMixin, money, str_enum, uuid_pk
from app.models.enums import (
    ActorType,
    BookingKind,
    BookingSource,
    BookingStatus,
    PaymentMethod,
)


class Booking(TimestampMixin, Base):
    """An appointment or a time block.

    blocked_until = end_at + buffer at the moment of booking. The exclusion constraint
    guarantees that active bookings of one barber never overlap — this is the source of truth
    against double booking; Redis holds are only a UX layer on top.
    """

    __tablename__ = "bookings"
    __table_args__ = (
        ExcludeConstraint(
            ("barber_id", "="),
            (text("tstzrange(start_at, blocked_until, '[)')"), "&&"),
            name="ex_bookings_no_overlap",
            using="gist",
            where=text("status IN ('pending', 'confirmed')"),
        ),
        CheckConstraint("end_at > start_at", name="time_order"),
        CheckConstraint("blocked_until >= end_at", name="blocked_until"),
        CheckConstraint("kind = 'block' OR client_id IS NOT NULL", name="client_required"),
        CheckConstraint("subtotal >= 0 AND bonus_spent >= 0", name="non_negative"),
        CheckConstraint("total_due = subtotal - bonus_spent - discount", name="total_due"),
        CheckConstraint("bonus_spent + discount <= subtotal", name="bonus_le_subtotal"),
        CheckConstraint("discount >= 0", name="discount"),
        CheckConstraint("prepaid_amount >= 0 AND prepay_due >= 0", name="prepaid"),
        CheckConstraint("voucher_amount >= 0", name="voucher_amount"),
        CheckConstraint("rating IS NULL OR rating BETWEEN 1 AND 5", name="rating"),
        Index("ix_bookings_barber_start", "barber_id", "start_at"),
        Index("ix_bookings_branch_start", "branch_id", "start_at"),
        Index("ix_bookings_client_start", "client_id", "start_at"),
        # public review feed of a barber, newest first
        Index(
            "ix_bookings_barber_reviews",
            "barber_id",
            "rated_at",
            postgresql_where=text("rating IS NOT NULL AND NOT review_hidden"),
        ),
        Index(
            "ux_bookings_idempotency",
            "client_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"))
    client_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clients.id"))
    barber_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("barbers.id"))
    kind: Mapped[BookingKind] = mapped_column(
        str_enum(BookingKind, "booking_kind"), default=BookingKind.APPOINTMENT
    )
    status: Mapped[BookingStatus] = mapped_column(
        str_enum(BookingStatus, "booking_status"), default=BookingStatus.CONFIRMED
    )
    source: Mapped[BookingSource] = mapped_column(
        str_enum(BookingSource, "booking_source"), default=BookingSource.MINIAPP
    )
    start_at: Mapped[datetime] = mapped_column()
    end_at: Mapped[datetime] = mapped_column()
    blocked_until: Mapped[datetime] = mapped_column()

    subtotal: Mapped[int] = money()
    bonus_spent: Mapped[int] = money()
    # promo code discount (salon's cost, like bonuses: the barber's share uses subtotal)
    discount: Mapped[int] = money()
    promo_code_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("promo_codes.id", ondelete="SET NULL")
    )
    total_due: Mapped[int] = money()
    paid_amount: Mapped[int | None] = money(nullable=True, default=None)
    payment_method: Mapped[PaymentMethod | None] = mapped_column(
        str_enum(PaymentMethod, "payment_method")
    )

    # money received before the visit (confirmed QR transfers, deposits)
    prepaid_amount: Mapped[int] = money()
    # prepayment the client must make before the booking is confirmed; 0 = none
    prepay_due: Mapped[int] = money()
    # part of the bill covered by gift certificates / subscription visits (not money today)
    voucher_amount: Mapped[int] = money()
    # the client tapped "I paid" and the salon has not checked it yet
    payment_claimed_at: Mapped[datetime | None] = mapped_column()
    comment: Mapped[str | None] = mapped_column(Text)
    admin_note: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(64))
    created_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    cancelled_by: Mapped[ActorType | None] = mapped_column(str_enum(ActorType, "actor_type"))
    cancelled_at: Mapped[datetime | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column()
    # barber's commission at completion time: later rate changes do not rewrite payouts
    barber_commission_bp: Mapped[int | None] = mapped_column(SmallInteger)
    rating: Mapped[int | None] = mapped_column(SmallInteger)  # 1..5 from the post-visit poll
    rated_at: Mapped[datetime | None] = mapped_column()
    # written review of this visit (one per completed booking); hidden = moderated by the salon
    review_text: Mapped[str | None] = mapped_column(Text)
    review_hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # the client tapped "I'll come" in a reminder
    client_confirmed_at: Mapped[datetime | None] = mapped_column()
    # "time for a haircut" message sent for this (last) visit
    revisit_nudged_at: Mapped[datetime | None] = mapped_column()
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    services: Mapped[list[BookingService]] = relationship(
        back_populates="booking",
        cascade="all, delete-orphan",
        order_by="BookingService.position",
        lazy="raise",
    )

    # eager_defaults: fetch server-generated created_at/updated_at via RETURNING (async-safe)
    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}  # noqa: RUF012


class BookingService(Base):
    """Snapshot of a service at booking time: later price changes don't alter history."""

    __tablename__ = "booking_services"

    id: Mapped[uuid.UUID] = uuid_pk()
    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), index=True
    )
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL")
    )
    name_snapshot: Mapped[I18n] = mapped_column()
    duration_min: Mapped[int] = mapped_column(SmallInteger)
    price: Mapped[int] = money()
    position: Mapped[int] = mapped_column(SmallInteger, default=0)

    booking: Mapped[Booking] = relationship(back_populates="services", lazy="raise")


class BookingReminder(Base):
    __tablename__ = "booking_reminders"

    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), primary_key=True
    )
    offset_min: Mapped[int] = mapped_column(Integer, primary_key=True)
    sent_at: Mapped[datetime] = mapped_column()
