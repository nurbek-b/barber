"""Booking from the public web page (no Telegram): name + phone, pending until the salon calls.

The phone is not verified (no SMS yet), so:
* the booking is PENDING and the salon confirms it by phone;
* nothing about an existing client with that phone is revealed (no bookings, no bonuses);
* the client gets no Telegram message about it (someone may have typed another person's number);
* bonuses are not spent; promo codes work (their per-client limits use that phone's client).

Flow: /hold places the usual 5-minute hold for the client found or created by phone and returns
a short-lived signed token binding hold and client; /promo and /confirm need that token.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import RateLimitedError, UnauthorizedError, ValidationAppError
from app.core.redis import hit_rate_limit
from app.domain.pricing import Quote
from app.models import Booking, Client
from app.models.enums import ActorType, BookingSource, BookingStatus
from app.services.audit import Actor
from app.services.bookings import ClientBookingService, PlacedHold
from app.services.client_registry import new_referral_code, normalize_phone
from app.services.slot_cache import SlotCache

TOKEN_TTL = timedelta(minutes=10)
HOLDS_PER_IP_HOUR = 30
BOOKINGS_PER_IP_HOUR = 6


@dataclass(frozen=True, slots=True)
class WebHold:
    placed: PlacedHold
    token: str


class PublicBookingService:
    def __init__(
        self, session: AsyncSession, redis: Redis, cache: SlotCache, settings: Settings
    ) -> None:
        self.session = session
        self.redis = redis
        self.settings = settings
        self.bookings = ClientBookingService(session, redis, cache)

    def _secret(self) -> str:
        secret = self.settings.jwt_secret.get_secret_value()
        if not secret:
            raise RuntimeError("JWT_SECRET is not configured")
        return secret

    async def _limit(self, key: str, limit: int) -> None:
        if await hit_rate_limit(self.redis, key, limit, 3600):
            raise RateLimitedError("Too many attempts, try later", headers={"Retry-After": "600"})

    async def _client(self, branch_id: uuid.UUID, name: str, phone: str) -> Client:
        normalized = normalize_phone(phone)
        client = await self.session.scalar(
            select(Client).where(Client.branch_id == branch_id, Client.phone == normalized).limit(1)
        )
        if client is None:
            client = Client(
                branch_id=branch_id,
                name=name.strip()[:200],
                phone=normalized,
                referral_code=new_referral_code(),
            )
            self.session.add(client)
            await self.session.commit()
        if client.is_blocked:
            raise ValidationAppError(
                "Online booking is not available, please call the salon", code="client_blocked"
            )
        return client

    def _token(self, client_id: uuid.UUID, hold_id: str, now: datetime) -> str:
        payload = {
            "typ": "webhold",
            "sub": str(client_id),
            "hold": hold_id,
            "exp": int((now + TOKEN_TTL).timestamp()),
        }
        return jwt.encode(payload, self._secret(), algorithm=self.settings.jwt_algorithm)

    async def _from_token(self, token: str) -> tuple[Client, str]:
        try:
            payload = jwt.decode(
                token,
                self._secret(),
                algorithms=[self.settings.jwt_algorithm],
                options={"require": ["exp", "sub", "hold", "typ"]},
            )
        except jwt.PyJWTError as exc:
            raise UnauthorizedError("The selection expired, pick the time again") from exc
        if payload.get("typ") != "webhold":
            raise UnauthorizedError()
        client = await self.session.get(Client, uuid.UUID(payload["sub"]))
        if client is None:
            raise UnauthorizedError()
        return client, str(payload["hold"])

    async def hold(
        self,
        branch_id: uuid.UUID,
        *,
        name: str,
        phone: str,
        barber_id: uuid.UUID | None,
        service_ids: list[uuid.UUID],
        start_at: datetime,
        ip: str,
        now: datetime,
    ) -> WebHold:
        await self._limit(f"pub:hold:{ip}", HOLDS_PER_IP_HOUR)
        client = await self._client(branch_id, name, phone)
        placed = await self.bookings.place_hold(
            branch_id,
            client,
            barber_id=barber_id,
            service_ids=service_ids,
            start_at=start_at,
            now=now,
        )
        return WebHold(placed=placed, token=self._token(client.id, placed.hold.id, now))

    async def promo(
        self, branch_id: uuid.UUID, token: str, code: str, now: datetime
    ) -> tuple[Quote, str]:
        client, hold_id = await self._from_token(token)
        return await self.bookings.check_promo(branch_id, client, hold_id, code, now)

    async def confirm(
        self,
        branch_id: uuid.UUID,
        *,
        token: str,
        comment: str | None,
        promo_code: str | None,
        idempotency_key: str,
        ip: str,
        now: datetime,
    ) -> Booking:
        await self._limit(f"pub:book:{ip}", BOOKINGS_PER_IP_HOUR)
        client, hold_id = await self._from_token(token)
        created = await self.bookings.create(
            branch_id,
            client,
            Actor(type=ActorType.CLIENT, id=client.id, ip=ip),
            hold_id=hold_id,
            comment=comment,
            bonus_to_spend=0,
            idempotency_key=idempotency_key,
            now=now,
            promo_code=promo_code,
            status=BookingStatus.PENDING,
            source=BookingSource.WEB,
            notify_client=False,
        )
        return created.booking
