from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import Field

from app.models.enums import PaymentMethod
from app.schemas.common import ApiModel

VoucherState = Literal["active", "used", "expired", "cancelled"]


class CertificateIn(ApiModel):
    amount: int = Field(gt=0, le=10**10)
    expires_on: date | None = None
    buyer_name: str | None = Field(default=None, max_length=200)
    recipient_name: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=500)
    payment_method: PaymentMethod = PaymentMethod.CASH


class CertificateOut(ApiModel):
    id: uuid.UUID
    code: str
    amount: int
    balance: int
    state: VoucherState
    buyer_name: str | None
    recipient_name: str | None
    note: str | None
    expires_on: date | None
    payment_method: PaymentMethod
    sold_at: datetime


class CertificateBalanceOut(ApiModel):
    code: str
    balance: int
    expires_on: date | None
    state: VoucherState


class PlanIn(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    service_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    visits: int = Field(ge=1, le=100)
    price: int = Field(gt=0, le=10**10)
    valid_days: int = Field(ge=1, le=1000)
    is_active: bool = True


class PlanOut(PlanIn):
    id: uuid.UUID


class SubscriptionSellIn(ApiModel):
    client_id: uuid.UUID
    plan_id: uuid.UUID
    payment_method: PaymentMethod = PaymentMethod.CASH


class SubscriptionOut(ApiModel):
    id: uuid.UUID
    client_id: uuid.UUID
    client_name: str
    name: str
    service_ids: list[uuid.UUID]
    visits_total: int
    visits_left: int
    price: int
    expires_on: date
    state: VoucherState
    sold_at: datetime


class ApplyCertificateIn(ApiModel):
    code: str = Field(min_length=4, max_length=32)
    amount: int | None = Field(default=None, gt=0, le=10**10, description="NULL = as much as fits")


class ApplySubscriptionIn(ApiModel):
    subscription_id: uuid.UUID


class VoucherUseOut(ApiModel):
    id: uuid.UUID
    kind: Literal["certificate", "subscription"]
    label: str
    amount: int
    created_at: datetime


class MySubscriptionOut(ApiModel):
    id: uuid.UUID
    name: str
    visits_total: int
    visits_left: int
    expires_on: date
    state: VoucherState
