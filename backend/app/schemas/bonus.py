from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field, model_validator

from app.models.enums import BonusTxType, LevelRule
from app.schemas.common import ApiModel, I18nName, Money

BasisPoints = Annotated[int, Field(ge=0, le=10_000, description="Basis points: 500 = 5%")]


class LevelOut(ApiModel):
    id: uuid.UUID
    name_i18n: dict[str, str]
    min_visits: int
    min_spent: int
    cashback_bp: int
    color: str | None
    sort_order: int


class LevelIn(ApiModel):
    name_i18n: I18nName
    min_visits: int = Field(default=0, ge=0, le=100_000)
    min_spent: Money = 0
    cashback_bp: BasisPoints
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    sort_order: int = Field(default=0, ge=0, le=1000)


class BonusSettingsOut(ApiModel):
    enabled: bool
    base_cashback_bp: int
    max_spend_bp: int
    lifetime_days: int | None
    level_rule: LevelRule
    welcome_enabled: bool
    welcome_amount: int
    birthday_enabled: bool
    birthday_amount: int
    birthday_days_before: int
    referral_enabled: bool
    referrer_amount: int
    referee_amount: int
    expiry_warning_days: int


class BonusSettingsIn(ApiModel):
    enabled: bool
    base_cashback_bp: BasisPoints
    max_spend_bp: BasisPoints
    lifetime_days: int | None = Field(default=None, ge=1, le=3650, description="NULL = never")
    level_rule: LevelRule = LevelRule.ANY
    welcome_enabled: bool = False
    welcome_amount: Money = 0
    birthday_enabled: bool = False
    birthday_amount: Money = 0
    birthday_days_before: int = Field(default=0, ge=0, le=30)
    referral_enabled: bool = False
    referrer_amount: Money = 0
    referee_amount: Money = 0
    expiry_warning_days: int = Field(default=3, ge=0, le=60)

    @model_validator(mode="after")
    def _amounts(self) -> BonusSettingsIn:
        if self.welcome_enabled and self.welcome_amount <= 0:
            raise ValueError("welcome_amount must be positive when enabled")
        if self.birthday_enabled and self.birthday_amount <= 0:
            raise ValueError("birthday_amount must be positive when enabled")
        if self.referral_enabled and self.referrer_amount + self.referee_amount <= 0:
            raise ValueError("referral amounts must be positive when enabled")
        return self


class BonusTransactionOut(ApiModel):
    id: uuid.UUID
    type: BonusTxType
    amount: int
    balance_after: int
    booking_id: uuid.UUID | None
    expires_at: datetime | None
    comment: str | None
    created_at: datetime


class ExpiringOut(ApiModel):
    amount: int
    expires_at: datetime


class BonusSummaryOut(ApiModel):
    enabled: bool
    balance: int
    level: LevelOut | None
    next_level: LevelOut | None
    visits_left: int = Field(description="Visits still needed for the next level")
    spent_left: int = Field(description="Amount still to pay for the next level")
    level_rule: LevelRule
    cashback_bp: int
    max_spend_bp: int
    expiring: list[ExpiringOut]


class TransactionPage(ApiModel):
    items: list[BonusTransactionOut]
    next_cursor: str | None


class ReferralOut(ApiModel):
    code: str
    miniapp_link: str
    bot_link: str
    invited: int
    rewarded: int
    referrer_amount: int
    referee_amount: int
    enabled: bool


class AdjustIn(ApiModel):
    amount: int = Field(
        ge=-(10**10), le=10**10, description="Positive — credit, negative — debit; not 0"
    )
    comment: str = Field(min_length=3, max_length=500)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ClientBonusOut(ApiModel):
    balance: int
    ledger_balance: int = Field(description="Sum of the ledger; must equal balance")
    level: LevelOut | None
    visits_count: int
    total_spent: int
    transactions: list[BonusTransactionOut]
