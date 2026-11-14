from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, money, uuid_pk


class User(TimestampMixin, Base):
    """Telegram identity."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str] = mapped_column(String(128), default="")
    last_name: Mapped[str | None] = mapped_column(String(128))
    language_code: Mapped[str | None] = mapped_column(String(10))
    photo_url: Mapped[str | None] = mapped_column(String(512))
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)
    bot_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Client(TimestampMixin, Base):
    """A salon customer. user_id is NULL for clients created by phone call."""

    __tablename__ = "clients"
    __table_args__ = (
        UniqueConstraint("branch_id", "user_id"),
        Index("ix_clients_branch_phone", "branch_id", "phone"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str | None] = mapped_column(String(20))
    birthday: Mapped[date | None] = mapped_column(Date)
    language: Mapped[str] = mapped_column(String(5), default="ru", server_default="ru")
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(50)), default=list, server_default=text("'{}'")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    level_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("loyalty_levels.id", ondelete="SET NULL")
    )
    bonus_balance: Mapped[int] = money()
    total_spent: Mapped[int] = money()
    visits_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    no_show_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    referral_code: Mapped[str] = mapped_column(String(16), unique=True)
    referred_by_client_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL")
    )
