from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, model_validator

from app.schemas.common import ApiModel, I18nName, I18nText, Money

# ---------- categories ----------


class ServiceCategoryIn(ApiModel):
    name_i18n: I18nName
    sort_order: int = Field(default=0, ge=0, le=10_000)


class ServiceCategoryPatch(ApiModel):
    name_i18n: I18nName | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10_000)


class ServiceCategoryOut(ApiModel):
    id: uuid.UUID
    name_i18n: dict[str, str]
    sort_order: int


# ---------- services ----------


class ServiceIn(ApiModel):
    category_id: uuid.UUID | None = None
    name_i18n: I18nName
    description_i18n: I18nText = Field(default_factory=dict)
    duration_min: int = Field(ge=5, le=600)
    base_price: Money
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0, le=10_000)


class ServicePatch(ApiModel):
    category_id: uuid.UUID | None = None
    name_i18n: I18nName | None = None
    description_i18n: I18nText | None = None
    duration_min: int | None = Field(default=None, ge=5, le=600)
    base_price: Money | None = None
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10_000)


class ServiceOut(ApiModel):
    id: uuid.UUID
    category_id: uuid.UUID | None
    name_i18n: dict[str, str]
    description_i18n: dict[str, str]
    duration_min: int
    base_price: int
    is_active: bool
    sort_order: int


# ---------- barbers ----------


class BarberServiceIn(ApiModel):
    service_id: uuid.UUID
    price: Money | None = Field(default=None, description="NULL → service base_price")
    duration_min: int | None = Field(default=None, ge=5, le=600)
    is_active: bool = True


class BarberServiceOut(ApiModel):
    service_id: uuid.UUID
    price: int | None
    duration_min: int | None
    is_active: bool
    effective_price: int
    effective_duration_min: int


COMMISSION_DESCRIPTION = (
    "Master's share of the services price, basis points: 4000 = 40 %. Owner only."
)


class BarberIn(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    commission_bp: int = Field(default=0, ge=0, le=10_000, description=COMMISSION_DESCRIPTION)
    specialization_i18n: I18nText = Field(default_factory=dict)
    bio_i18n: I18nText = Field(default_factory=dict)
    sort_order: int = Field(default=0, ge=0, le=10_000)
    is_active: bool = True
    is_bookable_online: bool = True
    telegram_chat_id: int | None = None
    services: list[BarberServiceIn] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def _unique_services(self) -> BarberIn:
        ids = [item.service_id for item in self.services]
        if len(ids) != len(set(ids)):
            raise ValueError("services contain duplicates")
        return self


class BarberPatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    commission_bp: int | None = Field(
        default=None, ge=0, le=10_000, description=COMMISSION_DESCRIPTION
    )
    specialization_i18n: I18nText | None = None
    bio_i18n: I18nText | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10_000)
    is_active: bool | None = None
    is_bookable_online: bool | None = None
    telegram_chat_id: int | None = None


class BarberServicesPut(ApiModel):
    services: list[BarberServiceIn] = Field(max_length=200)

    @model_validator(mode="after")
    def _unique_services(self) -> BarberServicesPut:
        ids = [item.service_id for item in self.services]
        if len(ids) != len(set(ids)):
            raise ValueError("services contain duplicates")
        return self


class BarberOut(ApiModel):
    id: uuid.UUID
    name: str
    photo_url: str | None
    specialization_i18n: dict[str, str]
    bio_i18n: dict[str, str]
    rating: float | None = Field(description="0..5, null when there are no ratings yet")
    rating_count: int
    sort_order: int
    is_active: bool
    is_bookable_online: bool
    telegram_chat_id: int | None
    portfolio: list[str] = Field(default_factory=list)
    commission_bp: int
    has_schedule: bool = Field(description="false: no weekly hours, clients cannot book")
    payment_qr_url: str | None = Field(default=None, description="Bank QR for client payments")


class BarberDetailOut(BarberOut):
    services: list[BarberServiceOut]


# ---------- mini app (public) ----------


class PublicBarberOut(ApiModel):
    id: uuid.UUID
    name: str
    photo_url: str | None
    specialization_i18n: dict[str, str]
    bio_i18n: dict[str, str]
    rating: float | None
    rating_count: int


class PublicBarberProfileOut(PublicBarberOut):
    portfolio: list[str] = Field(description="Photos of the barber's work, /media/... URLs")


class ReviewOut(ApiModel):
    booking_id: uuid.UUID
    rating: int
    text: str | None
    author: str = Field(description="First name and initial, e.g. 'Бектур А.'")
    services: list[dict[str, str]] = Field(description="name_i18n of the visit's services")
    created_at: datetime


class ReviewPage(ApiModel):
    items: list[ReviewOut]
    next_cursor: str | None


class ReviewIn(ApiModel):
    rating: int = Field(ge=1, le=5)
    text: str | None = Field(default=None, max_length=1000)


class AdminReviewOut(ApiModel):
    booking_id: uuid.UUID
    barber_id: uuid.UUID
    barber_name: str
    client_id: uuid.UUID | None
    client_name: str
    rating: int
    text: str | None
    hidden: bool
    created_at: datetime


class ReviewVisibilityIn(ApiModel):
    hidden: bool


class PublicServiceOut(ApiModel):
    id: uuid.UUID
    category_id: uuid.UUID | None
    name_i18n: dict[str, str]
    description_i18n: dict[str, str]
    duration_min: int = Field(description="For 'any barber': minimum among barbers")
    duration_max_min: int
    price_min: int = Field(description="Equal to price_max when a barber is chosen")
    price_max: int


class PublicCatalogOut(ApiModel):
    categories: list[ServiceCategoryOut]
    services: list[PublicServiceOut]
