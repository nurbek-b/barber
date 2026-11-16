from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from app.models.enums import ActorType, AdminRole, PaymentMethod, PromoKind
from app.schemas.common import SUPPORTED_LANGUAGES, ApiModel, Money

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
    prepay_required: bool = False


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
    prepay_required: bool | None = Field(
        default=None, description="Ask this client to prepay online bookings"
    )

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


REVIEW_SITES = ("2gis", "google")


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
    revisit_after_days: int
    review_links: dict[str, str] = Field(default_factory=dict)
    payment_qr_url: str | None = None
    payment_note: str | None = None
    prepay_percent: int = 0
    prepay_after_no_shows: int = 1
    prepay_timeout_min: int = 120


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
    review_links: dict[str, str] = Field(
        default_factory=dict, description='Map review pages: {"2gis": url, "google": url}'
    )
    payment_note: str | None = Field(
        default=None, max_length=300, description="Shown next to the QR: bank, recipient name"
    )
    prepay_percent: int = Field(default=0, ge=0, le=100, description="0 = no prepayment")
    prepay_after_no_shows: int = Field(default=1, ge=1, le=20)
    prepay_timeout_min: int = Field(
        default=120, ge=0, le=7 * 24 * 60, description="Cancel unpaid bookings after; 0 = never"
    )

    @field_validator("review_links")
    @classmethod
    def _review_links(cls, value: dict[str, str]) -> dict[str, str]:
        clean = {key: url.strip() for key, url in value.items() if url and url.strip()}
        if any(key not in REVIEW_SITES for key in clean):
            raise ValueError(f"review sites must be among {REVIEW_SITES}")
        if any(not url.startswith("https://") or len(url) > 500 for url in clean.values()):
            raise ValueError("review links must be https:// URLs up to 500 characters")
        return clean

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

    revisit_after_days: int = Field(default=30, ge=0, le=365, description="0 = off")


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
    discount: int = Field(default=0, description="Promo code discounts")
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


PROMO_CODE_PATTERN = r"^[A-Za-z0-9_-]{3,32}$"


class PromoCodeIn(ApiModel):
    code: str = Field(pattern=PROMO_CODE_PATTERN, description="Letters, digits, - and _")
    kind: PromoKind
    value: int = Field(gt=0, description="percent: basis points (2000 = 20 %); fixed: tyiyn")
    max_discount: Money | None = Field(default=None, description="Cap for percent codes")
    min_subtotal: Money = 0
    valid_from: date | None = None
    valid_to: date | None = None
    max_uses: int | None = Field(default=None, gt=0)
    max_uses_per_client: int = Field(default=1, gt=0, le=1000)
    first_visit_only: bool = False
    is_active: bool = True
    description: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _check(self) -> PromoCodeIn:
        if self.kind is PromoKind.PERCENT and self.value > 10_000:
            raise ValueError("percent value is at most 10000 (100 %)")
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to is before valid_from")
        return self


class PromoCodePatch(ApiModel):
    is_active: bool | None = None
    valid_to: date | None = None
    max_uses: int | None = Field(default=None, gt=0)
    description: str | None = Field(default=None, max_length=200)


class PromoCodeOut(ApiModel):
    id: uuid.UUID
    code: str
    kind: PromoKind
    value: int
    max_discount: int | None
    min_subtotal: int
    valid_from: date | None
    valid_to: date | None
    max_uses: int | None
    max_uses_per_client: int
    first_visit_only: bool
    is_active: bool
    description: str | None
    uses: int
    created_at: datetime


class SegmentIn(ApiModel):
    kind: Literal["all", "inactive", "never_visited", "birthday_month", "tag"]
    days: int | None = Field(default=None, ge=1, le=3650, description="inactive: N+ days")
    tag: str | None = Field(default=None, max_length=50)


class BroadcastIn(ApiModel):
    segment: SegmentIn
    texts: dict[str, str] = Field(description="{'ru': required, 'ky', 'en'}")
    promo_code_id: uuid.UUID | None = None
    book_button: bool = True


class SegmentCountOut(ApiModel):
    recipients: int


class BroadcastOut(ApiModel):
    id: uuid.UUID
    texts: dict[str, str]
    segment: dict[str, Any]
    promo_code: str | None
    recipients: int
    created_at: datetime


# ---------------- barber payouts ----------------


class PayoutBalanceOut(ApiModel):
    barber_id: uuid.UUID
    barber_name: str
    commission_bp: int
    earned: int = Field(description="Barber's share of completed visits up to `until`")
    paid: int
    due: int = Field(description="earned - paid; negative = paid in advance")
    last_paid_on: date | None


class PayoutIn(ApiModel):
    barber_id: uuid.UUID
    amount: int = Field(gt=0, le=10**12)
    paid_on: date
    method: PaymentMethod = PaymentMethod.CASH
    note: str | None = Field(default=None, max_length=300)


class PayoutOut(ApiModel):
    id: uuid.UUID
    barber_id: uuid.UUID
    barber_name: str
    amount: int
    paid_on: date
    method: PaymentMethod
    note: str | None
    created_at: datetime


# ---------------- booking funnel ----------------


class FunnelStepOut(ApiModel):
    step: str
    sessions: int
    rate: float = Field(description="Share of sessions that opened the app, 0..1")


class FunnelOut(ApiModel):
    source: str
    steps: list[FunnelStepOut]
