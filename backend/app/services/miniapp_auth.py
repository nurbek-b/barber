from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ForbiddenError, UnauthorizedError, ValidationAppError
from app.core.security.initdata import (
    InitData,
    InitDataError,
    parse_init_data,
    parse_signed_contact,
)
from app.models import Client, User
from app.models.enums import ActorType
from app.services.audit import Actor, AuditService
from app.services.client_registry import (
    REFERRAL_PREFIX,
    ClientRegistry,
    new_referral_code,
    normalize_phone,
)

__all__ = [
    "REFERRAL_PREFIX",
    "MiniappAuthService",
    "MiniappIdentity",
    "new_referral_code",
    "normalize_phone",
]


@dataclass(slots=True)
class MiniappIdentity:
    init_data: InitData
    user: User
    client: Client
    is_new: bool

    @property
    def actor(self) -> Actor:
        return Actor(type=ActorType.CLIENT, id=self.client.id)


class MiniappAuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.registry = ClientRegistry(session)
        self.audit = AuditService(session)

    def parse(self, authorization: str | None) -> InitData:
        if not authorization:
            raise UnauthorizedError("Authorization header is missing")
        scheme, _, raw = authorization.partition(" ")
        if scheme.lower() != "tma" or not raw:
            raise UnauthorizedError("Expected 'Authorization: tma <initData>'")
        try:
            return parse_init_data(
                raw.strip(),
                self.settings.bot_token.get_secret_value(),
                self.settings.init_data_ttl_seconds,
            )
        except InitDataError as exc:
            raise UnauthorizedError(f"Invalid init data: {exc}", code="init_data_invalid") from exc

    async def authenticate(
        self, authorization: str | None, branch_id: uuid.UUID, default_language: str
    ) -> MiniappIdentity:
        init = self.parse(authorization)
        user = await self.registry.upsert_user(init.user)
        client, is_new = await self.registry.ensure_client(
            branch_id, user, start_param=init.start_param, default_language=default_language
        )
        if self.session.dirty or self.session.new or is_new:
            await self.session.commit()
        if client.is_blocked:
            raise ForbiddenError("Client is blocked", code="client_blocked")
        return MiniappIdentity(init_data=init, user=user, client=client, is_new=is_new)

    async def save_phone(self, identity: MiniappIdentity, signed_contact: str) -> Client:
        try:
            contact = parse_signed_contact(
                signed_contact,
                self.settings.bot_token.get_secret_value(),
                self.settings.init_data_ttl_seconds,
            )
        except InitDataError as exc:
            raise ValidationAppError(f"Invalid contact: {exc}", code="contact_invalid") from exc
        if contact.user_id != identity.user.telegram_id:
            raise ForbiddenError("Contact belongs to another user", code="contact_mismatch")
        client = identity.client
        before = client.phone
        client.phone = normalize_phone(contact.phone_number)
        if before != client.phone:
            self.audit.record(
                identity.actor,
                "client.phone",
                "client",
                client.id,
                before={"phone": before},
                after={"phone": client.phone},
            )
        await self.session.commit()
        return client
