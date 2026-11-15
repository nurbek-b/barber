from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import Field, field_validator, model_validator

from app.models.enums import ActorType, AdminRole
from app.schemas.common import SUPPORTED_LANGUAGES, ApiModel

# ---------------- clients ----------------


def clean_tags(value: list[str]) -> list[str]:
    return sorted({tag.strip().lower()[:50] for tag in value if tag.strip()})


class ClientRow(ApiModel):
    id: uuid.UUID
    name: str
    phone: str | None
    telegram_username: str | None
    language: str
    tags: list[str]
    is_blocked: bool
    level_id: uuid.UUID | None
    bonus_balance: int
    total_spent: int
    visits_count: int
    no_show_count: int
    last_visit_at: datetime | None
    created_at: datetime


class ClientPage(ApiModel):
    items: list[ClientRow]
    total: int
    limit: int
    offset: int


class ClientCard(ClientRow):
    birthday: date | None
    notes: str | None
    referral_code: str
    referred_by_client_id: uuid.UUID | None
    upcoming_count: int
    average_check: int


class ClientIn(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=7, max_length=20)
    birthday: date | None = None
    language: str = "ru"
    tags: list[str] = Field(default_factory=list, max_length=20)
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: list[str]) -> list[str]:
        return clean_tags(value)

    @field_validator("language")
    @classmethod
    def _lang(cls, value: str) -> str:
        if value not in SUPPORTED_LANGUAGES:
            raise ValueError(f"language must be one of {SUPPORTED_LANGUAGES}")
        return value


class ClientPatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, min_length=7, max_length=20)
    birthday: date | None = None
    language: str | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else clean_tags(value)

    @field_validator("language")
    @classmethod
    def _lang(cls, value: str | None) -> str | None:
        if value is not None and value not in SUPPORTED_LANGUAGES:
            raise ValueError(f"language must be one of {SUPPORTED_LANGUAGES}")
        return value


class BlockIn(ApiModel):
    blocked: bool
    reason: str | None = Field(default=None, max_length=500)


# ---------------- salon settings ----------------


class SalonSettingsOut(ApiModel):
    name: str
    timezone: str
    currency: str
    default_language: str
    slot_step_min: int
    buffer_min: int
    min_lead_time_min: int
    max_days_ahead: int
    cancel_min_hours: int
    reschedule_min_hours: int
    max_active_bookings_per_client: int
    reminder_offsets_min: list[int]
    admin_chat_id: int | None
    notify_barbers: bool
    notification_templates: dict[str, dict[str, str]]
    contacts: dict[str, str]
    logo_url: str | None
    gallery: list[str]


class GalleryPut(ApiModel):
    """Current gallery URLs in the new order; leaving one out deletes it."""

    urls: list[str] = Field(max_length=8)


class SalonSettingsIn(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    timezone: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    default_language: str
    slot_step_min: int = Field(ge=5, le=120)
    buffer_min: int = Field(ge=0, le=120)
    min_lead_time_min: int = Field(ge=0, le=7 * 24 * 60)
    max_days_ahead: int = Field(ge=1, le=365)
    cancel_min_hours: int = Field(ge=0, le=168)
    reschedule_min_hours: int = Field(ge=0, le=168)
    max_active_bookings_per_client: int = Field(ge=1, le=50)
    reminder_offsets_min: list[int] = Field(max_length=5)
    admin_chat_id: int | None = None
    notify_barbers: bool = False
    notification_templates: dict[str, dict[str, str]] = Field(default_factory=dict)
    contacts: dict[str, str] = Field(default_factory=dict)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, value: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("unknown timezone") from exc
        return value

    @field_validator("default_language")
    @classmethod
    def _lang(cls, value: str) -> str:
        if value not in SUPPORTED_LANGUAGES:
            raise ValueError(f"language must be one of {SUPPORTED_LANGUAGES}")
        return value

    @field_validator("reminder_offsets_min")
    @classmethod
    def _offsets(cls, value: list[int]) -> list[int]:
        if any(not 5 <= item <= 7 * 24 * 60 for item in value):
            raise ValueError("reminder offsets must be between 5 minutes and 7 days")
        return sorted(set(value), reverse=True)

    @field_validator("notification_templates")
    @classmethod
    def _templates(cls, value: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        from app.notify.templates import DEFAULTS

        unknown = set(value) - set(DEFAULTS)
        if unknown:
            raise ValueError(f"unknown templates: {sorted(unknown)}")
        for variants in value.values():
            if set(variants) - set(SUPPORTED_LANGUAGES):
                raise ValueError("unsupported template language")
            if any(len(text) > 2000 for text in variants.values()):
                raise ValueError("template is too long")
        return {key: {k: v for k, v in item.items() if v.strip()} for key, item in value.items()}


class TemplateDefaultsOut(ApiModel):
    templates: dict[str, dict[str, str]]


# ---------------- staff ----------------


class StaffOut(ApiModel):
    id: uuid.UUID
    login: str
    full_name: str
    role: AdminRole
    barber_id: uuid.UUID | None
    language: str
    is_active: bool
    telegram_linked: bool
    last_login_at: datetime | None
    created_at: datetime


class StaffIn(ApiModel):
    login: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=256)
    full_name: str = Field(default="", max_length=200)
    role: AdminRole
    barber_id: uuid.UUID | None = None
    language: str = "ru"

    @model_validator(mode="after")
    def _barber(self) -> StaffIn:
        if self.role is AdminRole.BARBER and self.barber_id is None:
            raise ValueError("barber accounts must be linked to a barber")
        if self.role is not AdminRole.BARBER and self.barber_id is not None:
            raise ValueError("only barber accounts are linked to a barber")
        return self


class StaffPatch(ApiModel):
    full_name: str | None = Field(default=None, max_length=200)
    role: AdminRole | None = None
    barber_id: uuid.UUID | None = None
    language: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=10, max_length=256)


# ---------------- audit ----------------


class AuditOut(ApiModel):
    id: int
    actor_type: ActorType
    actor_id: uuid.UUID | None
    actor_name: str | None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    ip: str | None
    created_at: datetime


class AuditPage(ApiModel):
    items: list[AuditOut]
    total: int
    limit: int
    offset: int


# ---------------- dashboard & finance ----------------


class RevenuePoint(ApiModel):
    date: date
    revenue: int = Field(description="Paid with money (paid_amount of completed bookings)")
    bookings: int


class BarberLoad(ApiModel):
    barber_id: uuid.UUID
    name: str
    booked_minutes: int
    working_minutes: int
    load_percent: int
    bookings: int


class DashboardOut(ApiModel):
    today: date
    timezone: str
    currency: str
    bookings_today: int
    bookings_today_by_status: dict[str, int]
    revenue_day: int
    revenue_week: int
    revenue_month: int
    average_check: int = Field(description="Month: revenue / completed visits")
    new_clients_month: int
    barbers: list[BarberLoad]
    revenue_chart: list[RevenuePoint]
    upcoming: list[dict[str, Any]]


class FinanceTotals(ApiModel):
    bookings: int
    subtotal: int
    bonus_spent: int
    total_due: int
    paid: int
    master_share: int = Field(description="Barbers' commission: % of subtotal, see commission_bp")


class FinanceByBarber(FinanceTotals):
    barber_id: uuid.UUID
    name: str
    commission_bp: int = Field(description="Current rate; past visits keep their own rate")


class FinanceByService(ApiModel):
    service_id: uuid.UUID | None
    name_i18n: dict[str, str]
    count: int
    revenue: int


class FinanceByMethod(ApiModel):
    payment_method: str | None
    bookings: int
    paid: int


class FinanceReportOut(ApiModel):
    date_from: date
    date_to: date
    currency: str
    totals: FinanceTotals
    by_barber: list[FinanceByBarber]
    by_service: list[FinanceByService]
    by_payment_method: list[FinanceByMethod]
    daily: list[RevenuePoint]
