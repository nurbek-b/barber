from __future__ import annotations

import uuid
from datetime import date

from pydantic import Field, field_validator

from app.schemas.common import SUPPORTED_LANGUAGES, ApiModel


class ClientMe(ApiModel):
    id: uuid.UUID
    telegram_id: int
    name: str
    phone: str | None
    birthday: date | None
    language: str
    bonus_balance: int
    referral_code: str
    is_new: bool = Field(description="Created by this request")


class ClientMePatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    language: str | None = None
    birthday: date | None = Field(default=None, description="Can be set once; then via admin")

    @field_validator("language")
    @classmethod
    def _lang(cls, value: str | None) -> str | None:
        if value is not None and value not in SUPPORTED_LANGUAGES:
            raise ValueError(f"language must be one of {SUPPORTED_LANGUAGES}")
        return value

    @field_validator("birthday")
    @classmethod
    def _birthday(cls, value: date | None) -> date | None:
        if value is not None and not (date(1900, 1, 1) <= value <= date.today()):
            raise ValueError("birthday is out of range")
        return value


class PhoneIn(ApiModel):
    contact: str = Field(
        min_length=10,
        max_length=4096,
        description="Raw signed string from requestContact(): contact=...&auth_date=...&hash=...",
    )


class SalonPublicOut(ApiModel):
    name: str
    timezone: str
    currency: str
    default_language: str
    slot_step_min: int
    max_days_ahead: int
    cancel_min_hours: int
    reschedule_min_hours: int
    contacts: dict[str, str]
    logo_url: str | None = None
    gallery: list[str] = Field(default_factory=list)
