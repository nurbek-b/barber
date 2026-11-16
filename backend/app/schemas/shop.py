from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, field_validator

from app.models.enums import PaymentMethod
from app.models.shop import OrderStatus
from app.schemas.common import ApiModel, I18nName


class ProductIn(ApiModel):
    name_i18n: I18nName
    description_i18n: dict[str, str] = Field(default_factory=dict)
    price: int = Field(gt=0, le=10**10)
    stock: int | None = Field(default=None, ge=0, le=100_000, description="NULL = not tracked")
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0, le=1000)


class ProductOut(ApiModel):
    id: uuid.UUID
    name_i18n: dict[str, str]
    description_i18n: dict[str, str]
    price: int
    photo_url: str | None
    stock: int | None
    is_active: bool
    sort_order: int


class OrderLineIn(ApiModel):
    product_id: uuid.UUID
    quantity: int = Field(ge=1, le=99)


class OrderIn(ApiModel):
    items: list[OrderLineIn] = Field(min_length=1, max_length=30)
    comment: str | None = Field(default=None, max_length=500)


class OrderItemOut(ApiModel):
    product_id: uuid.UUID | None
    name_i18n: dict[str, str]
    price: int
    quantity: int


class OrderOut(ApiModel):
    id: uuid.UUID
    number: int
    status: OrderStatus
    items: list[OrderItemOut]
    total: int
    paid_amount: int
    comment: str | None
    created_at: datetime
    version: int


class AdminOrderOut(OrderOut):
    client_id: uuid.UUID
    client_name: str
    client_phone: str | None


class OrderPaymentOut(ApiModel):
    order_id: uuid.UUID
    status: OrderStatus
    qr_url: str | None
    note: str | None
    currency: str
    total: int
    amount_left: int


class OrderStatusIn(ApiModel):
    version: int
    status: OrderStatus
    payment_method: PaymentMethod | None = Field(
        default=None, description="For 'paid' without a client claim (cash at pickup)"
    )

    @field_validator("status")
    @classmethod
    def _status(cls, value: OrderStatus) -> OrderStatus:
        if value in (OrderStatus.NEW, OrderStatus.PAYMENT_CLAIMED):
            raise ValueError("set by the client")
        return value
