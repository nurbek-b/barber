"""Registering Telegram users as salon clients. Shared by the Mini App and the bot, so that
whichever the person opens first, they get the same client record, referral and welcome bonus."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationAppError
from app.core.security.initdata import TelegramUser
from app.models import Client, User
from app.models.enums import ActorType
from app.repositories.clients import ClientRepository
from app.schemas.common import SUPPORTED_LANGUAGES
from app.services.audit import Actor, AuditService
from app.services.bonus import BonusService

REFERRAL_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no look-alike characters
REFERRAL_PREFIX = "ref_"


def new_referral_code() -> str:
    return "".join(secrets.choice(REFERRAL_ALPHABET) for _ in range(8))


def pick_language(code: str | None, default: str) -> str:
    if code:
        short = code.split("-")[0].lower()
        if short in SUPPORTED_LANGUAGES:
            return short
    return default


def normalize_phone(raw: str) -> str:
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not 7 <= len(digits) <= 15:
        raise ValidationAppError("Invalid phone number", code="invalid_phone")
    return f"+{digits}"


def referral_code_from(start_param: str | None) -> str | None:
    if start_param and start_param.startswith(REFERRAL_PREFIX):
        return start_param.removeprefix(REFERRAL_PREFIX)[:16] or None
    return None


class ClientRegistry:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.clients = ClientRepository(session)
        self.audit = AuditService(session)

    async def upsert_user(self, tg: TelegramUser) -> User:
        """Create or refresh the Telegram profile; concurrent first requests are safe."""
        values = {
            "username": tg.username,
            "first_name": tg.first_name,
            "last_name": tg.last_name,
            "language_code": tg.language_code,
            "photo_url": tg.photo_url,
            "is_premium": tg.is_premium,
        }
        user = await self.session.scalar(select(User).where(User.telegram_id == tg.id))
        if user is None:
            await self.session.execute(
                insert(User)
                .values(id=uuid.uuid4(), telegram_id=tg.id, **values)
                .on_conflict_do_nothing(index_elements=[User.telegram_id])
            )
            user = await self.session.scalar(select(User).where(User.telegram_id == tg.id))
            if user is None:  # pragma: no cover - impossible after insert
                raise RuntimeError("user upsert failed")
        else:
            for key, value in values.items():
                if value is not None and getattr(user, key) != value:
                    setattr(user, key, value)
            if user.bot_blocked:
                user.bot_blocked = False  # they talk to us again
        return user

    async def ensure_client(
        self,
        branch_id: uuid.UUID,
        user: User,
        *,
        start_param: str | None,
        default_language: str,
        now: datetime | None = None,
    ) -> tuple[Client, bool]:
        client = await self.clients.get_by_user(branch_id, user.id)
        if client is not None:
            return client, False

        referrer_id: uuid.UUID | None = None
        code = referral_code_from(start_param)
        if code:
            referrer = await self.clients.get_by_referral_code(branch_id, code)
            if referrer is not None and referrer.user_id != user.id:
                referrer_id = referrer.id

        for _ in range(5):
            own_code = new_referral_code()
            if not await self.clients.referral_code_exists(own_code):
                break
        else:  # pragma: no cover - 31^8 space
            raise RuntimeError("cannot allocate referral code")

        name = " ".join(part for part in (user.first_name, user.last_name) if part)
        result = await self.session.execute(
            insert(Client)
            .values(
                id=uuid.uuid4(),
                branch_id=branch_id,
                user_id=user.id,
                name=name[:200],
                language=pick_language(user.language_code, default_language),
                referral_code=own_code,
                referred_by_client_id=referrer_id,
            )
            .on_conflict_do_nothing(index_elements=[Client.branch_id, Client.user_id])
            .returning(Client.id)
        )
        created = result.scalar_one_or_none() is not None
        client = await self.clients.get_by_user(branch_id, user.id)
        if client is None:  # pragma: no cover
            raise RuntimeError("client upsert failed")
        if created:
            self.audit.record(
                Actor(type=ActorType.CLIENT, id=client.id),
                "client.register",
                "client",
                client.id,
                after={"referred_by": client.referred_by_client_id},
            )
            await BonusService(self.session).welcome(client.id, now or datetime.now(UTC))
        return client, created
