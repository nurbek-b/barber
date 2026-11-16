from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import Field, field_validator, model_validator

from app.models.enums import (
    BookingKind,
    BookingSource,
    BookingStatus,
    PaymentMethod,
)
from app.schemas.catalog import PublicBarberOut
from app.schemas.common import ApiModel, Money
from app.schemas.schedule import Slot

# ---------------- holds & quotes ----------------


class HoldIn(ApiModel):
    barber_id: uuid.UUID | None = Field(default=None, description="NULL = any barber")
    service_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    start_at: datetime
    reschedule_booking_id: uuid.UUID | None = Field(
        default=None, description="Set when the hold is for moving an existing booking"
    )

    @field_validator("start_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("start_at must include a timezone (UTC recommended)")
        return value


class QuoteLineOut(ApiModel):
    service_id: uuid.UUID
    name_i18n: dict[str, str]
    duration_min: int
    price: int


class QuoteOut(ApiModel):
    lines: list[QuoteLineOut]
    subtotal: int
    duration_min: int
    bonus_balance: int
    max_bonus_spend: int


class HoldOut(ApiModel):
    hold_id: str
    expires_at: datetime
    barber: PublicBarberOut
    start_at: datetime
    end_at: datetime
    quote: QuoteOut


# ---------------- client bookings ----------------


class BookingCreateIn(ApiModel):
    hold_id: str = Field(min_length=8, max_length=64)
    comment: str | None = Field(default=None, max_length=500)
    bonus_to_spend: Money = Field(default=0, description="Bonus units to pay with (≤ max)")


class RescheduleIn(ApiModel):
    hold_id: str = Field(min_length=8, max_length=64)


class CancelIn(ApiModel):
    reason: str | None = Field(default=None, max_length=500)


class BookingServiceOut(ApiModel):
    service_id: uuid.UUID | None
    name_i18n: dict[str, str]
    duration_min: int
    price: int


class BookingBarberOut(ApiModel):
    id: uuid.UUID
    name: str
    photo_url: str | None


class BookingOut(ApiModel):
    id: uuid.UUID
    status: BookingStatus
    barber: BookingBarberOut
    services: list[BookingServiceOut]
    start_at: datetime
    end_at: datetime
    subtotal: int
    bonus_spent: int
    total_due: int
    comment: str | None
    can_cancel: bool
    can_reschedule: bool
    created_at: datetime
    rating: int | None = None
    review_text: str | None = None
    can_review: bool = Field(default=False, description="Completed within 30 days, not moderated")


class BookingPage(ApiModel):
    items: list[BookingOut]
    next_cursor: str | None


class RepeatDraftOut(ApiModel):
    source_booking_id: uuid.UUID
    barber: PublicBarberOut | None = Field(description="NULL if the barber is no longer bookable")
    service_ids: list[uuid.UUID]
    missing_service_ids: list[uuid.UUID] = Field(
        description="Services from the last visit that are no longer offered"
    )


class SlotConflictDetails(ApiModel):
    alternatives: list[Slot]


# ---------------- admin ----------------


class NewClientIn(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=7, max_length=20)


class AdminBookingCreateIn(ApiModel):
    client_id: uuid.UUID | None = None
    client: NewClientIn | None = Field(
        default=None, description="Phone booking: found by phone or created"
    )
    barber_id: uuid.UUID
    service_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    start_at: datetime
    status: BookingStatus = BookingStatus.CONFIRMED
    comment: str | None = Field(default=None, max_length=500)
    admin_note: str | None = Field(default=None, max_length=2000)
    ignore_schedule: bool = Field(
        default=False, description="Allow outside working hours (overlaps are still rejected)"
    )
    notify_client: bool = True

    @model_validator(mode="after")
    def _check(self) -> AdminBookingCreateIn:
        if (self.client_id is None) == (self.client is None):
            raise ValueError("pass exactly one of client_id or client")
        if self.status not in (BookingStatus.CONFIRMED, BookingStatus.PENDING):
            raise ValueError("a new booking can be only pending or confirmed")
        if self.start_at.tzinfo is None:
            raise ValueError("start_at must include a timezone")
        return self


class AdminServiceLineIn(ApiModel):
    service_id: uuid.UUID
    price: Money | None = Field(default=None, description="Actual price; NULL = barber price")


class AdminBookingPatch(ApiModel):
    version: int
    services: list[AdminServiceLineIn] | None = Field(default=None, min_length=1, max_length=10)
    comment: str | None = Field(default=None, max_length=500)
    admin_note: str | None = Field(default=None, max_length=2000)
    payment_method: PaymentMethod | None = None
    paid_amount: Money | None = None


class StatusChangeIn(ApiModel):
    version: int
    status: BookingStatus
    reason: str | None = Field(default=None, max_length=500)
    payment_method: PaymentMethod | None = None
    paid_amount: Money | None = None


class MoveIn(ApiModel):
    version: int
    start_at: datetime
    barber_id: uuid.UUID | None = None
    ignore_schedule: bool = False


class BlockIn(ApiModel):
    barber_id: uuid.UUID
    start_at: datetime
    end_at: datetime
    comment: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _check(self) -> BlockIn:
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise ValueError("times must include a timezone")
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        if (self.end_at - self.start_at).days > 31:
            raise ValueError("a block can be at most 31 days")
        return self


class AdminClientRef(ApiModel):
    id: uuid.UUID
    name: str
    phone: str | None


class AdminBookingOut(ApiModel):
    id: uuid.UUID
    kind: BookingKind
    status: BookingStatus
    source: BookingSource
    barber: BookingBarberOut
    client: AdminClientRef | None
    services: list[BookingServiceOut]
    start_at: datetime
    end_at: datetime
    subtotal: int
    bonus_spent: int
    total_due: int
    paid_amount: int | None
    payment_method: PaymentMethod | None
    comment: str | None
    admin_note: str | None
    cancel_reason: str | None
    version: int
    created_at: datetime
    client_confirmed_at: datetime | None = Field(
        default=None, description="The client tapped 'I'll come' in a reminder"
    )


class AdminBookingPage(ApiModel):
    items: list[AdminBookingOut]
    total: int
    limit: int
    offset: int


class CalendarQuery(ApiModel):
    date_from: date
    date_to: date
