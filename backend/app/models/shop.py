"""Products sold at the salon and client orders (paid by bank QR, picked up at the salon)."""

from __future__ import annotations

import uuid
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, I18n, TimestampMixin, money, str_enum, uuid_pk


class OrderStatus(StrEnum):
    NEW = "new"  # waiting for payment
    PAYMENT_CLAIMED = "payment_claimed"  # the client says they paid
    PAID = "paid"
    READY = "ready"  # ready for pickup
    COMPLETED = "completed"  # picked up
    CANCELLED = "cancelled"


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price > 0", name="price_positive"),
        CheckConstraint("stock IS NULL OR stock >= 0", name="stock"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), index=True)
    name_i18n: Mapped[I18n] = mapped_column()
    description_i18n: Mapped[I18n] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    price: Mapped[int] = money(default=None)
    photo_url: Mapped[str | None] = mapped_column(String(512))
    stock: Mapped[int | None] = mapped_column(Integer)  # NULL = not tracked
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")


class Order(TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("total > 0 AND paid_amount >= 0", name="amounts"),
        Index("ix_orders_branch_created", "branch_id", "created_at"),
        Index("ix_orders_client", "client_id"),
        UniqueConstraint("branch_id", "number"),
        Index(
            "ux_orders_idempotency",
            "client_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"))
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer)  # short number for pickup, per branch
    status: Mapped[OrderStatus] = mapped_column(str_enum(OrderStatus, "order_status"))
    total: Mapped[int] = money(default=None)
    paid_amount: Mapped[int] = money()
    comment: Mapped[str | None] = mapped_column(String(500))
    idempotency_key: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="OrderItem.position",
    )


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (CheckConstraint("quantity BETWEEN 1 AND 99", name="quantity"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL")
    )
    name_snapshot: Mapped[I18n] = mapped_column()
    price: Mapped[int] = money(default=None)
    quantity: Mapped[int] = mapped_column(SmallInteger)
    position: Mapped[int] = mapped_column(SmallInteger, default=0)

    order: Mapped[Order] = relationship(back_populates="items", lazy="raise")
