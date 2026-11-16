"""Business actions behind bot handlers (handlers only translate Telegram ↔ these)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, ValidationAppError
from app.core.security.initdata import TelegramUser
from app.models import AdminUser, Barber, Booking, Client, SalonSettings, User
from app.models.enums import ACTIVE_BOOKING_STATUSES, ActorType, BookingKind, BookingStatus
from app.services.audit import Actor, AuditService
from app.services.bookings import ClientBookingService
from app.services.branches import BranchService
from app.services.client_registry import ClientRegistry, normalize_phone
from app.services.reviews import recompute_barber_rating
from app.services.slot_cache import SlotCache
from app.services.staff_link import PREFIX as STAFF_PREFIX
from app.services.staff_link import parse_token


@dataclass(frozen=True, slots=True)
class StartResult:
    client: Client
    salon: SalonSettings
    is_new: bool
    welcome_bonus: bool


class RateOutcome(StrEnum):
    OK = "ok"
    ALREADY = "already"
    UNAVAILABLE = "unavailable"


class VisitOutcome(StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    TOO_LATE = "too_late"
    UNAVAILABLE = "unavailable"


class BotActions:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.registry = ClientRegistry(session)
        self.branches = BranchService(session)
        self.audit = AuditService(session)

    async def _client_of(self, telegram_id: int) -> tuple[Client, SalonSettings] | None:
        branch_id = await self.branches.default_branch_id()
        salon = await self.branches.settings(branch_id)
        client = await self.session.scalar(
            select(Client)
            .join(User, User.id == Client.user_id)
            .where(User.telegram_id == telegram_id, Client.branch_id == branch_id)
        )
        return (client, salon) if client is not None else None

    async def start(self, tg: TelegramUser, args: str | None, now: datetime) -> StartResult:
        branch_id = await self.branches.default_branch_id()
        salon = await self.branches.settings(branch_id)
        user = await self.registry.upsert_user(tg)
        client, is_new = await self.registry.ensure_client(
            branch_id, user, start_param=args, default_language=salon.default_language, now=now
        )
        await self.session.commit()
        return StartResult(
            client=client,
            salon=salon,
            is_new=is_new,
            welcome_bonus=is_new and client.bonus_balance > 0,
        )

    async def save_contact(self, telegram_id: int, phone: str) -> str | None:
        found = await self._client_of(telegram_id)
        if found is None:
            return None
        client, _ = found
        try:
            normalized = normalize_phone(phone)
        except ValidationAppError:
            return None
        if client.phone != normalized:
            self.audit.record(
                Actor(type=ActorType.CLIENT, id=client.id),
                "client.phone",
                "client",
                client.id,
                before={"phone": client.phone},
                after={"phone": normalized},
            )
            client.phone = normalized
        await self.session.commit()
        return normalized

    async def upcoming(
        self, telegram_id: int, now: datetime, limit: int = 5
    ) -> tuple[Client | None, list[tuple[Booking, Barber]], SalonSettings | None]:
        found = await self._client_of(telegram_id)
        if found is None:
            return None, [], None
        client, salon = found
        rows = await self.session.execute(
            select(Booking, Barber)
            .join(Barber, Barber.id == Booking.barber_id)
            .where(
                Booking.client_id == client.id,
                Booking.kind == BookingKind.APPOINTMENT,
                Booking.status.in_(ACTIVE_BOOKING_STATUSES),
                Booking.start_at > now,
            )
            .order_by(Booking.start_at)
            .limit(limit)
        )
        return client, [(row[0], row[1]) for row in rows.all()], salon

    async def language_of(self, telegram_id: int, fallback: str | None) -> str:
        found = await self._client_of(telegram_id)
        if found is not None:
            return found[0].language
        return fallback or "ru"

    async def set_language(self, telegram_id: int, language: str) -> bool:
        found = await self._client_of(telegram_id)
        if found is None or language not in ("ru", "ky", "en"):
            return False
        found[0].language = language
        await self.session.commit()
        return True

    async def set_blocked(self, telegram_id: int, blocked: bool) -> None:
        await self.session.execute(
            update(User).where(User.telegram_id == telegram_id).values(bot_blocked=blocked)
        )
        await self.session.commit()

    async def rate(
        self, telegram_id: int, booking_id: uuid.UUID, rating: int, now: datetime
    ) -> RateOutcome:
        if not 1 <= rating <= 5:
            return RateOutcome.UNAVAILABLE
        booking = await self.session.scalar(
            select(Booking)
            .join(Client, Client.id == Booking.client_id)
            .join(User, User.id == Client.user_id)
            .where(Booking.id == booking_id, User.telegram_id == telegram_id)
            .with_for_update(of=Booking)
        )
        if booking is None or booking.status is not BookingStatus.COMPLETED:
            return RateOutcome.UNAVAILABLE
        if booking.rating is not None:
            return RateOutcome.ALREADY
        if now - (booking.completed_at or booking.end_at) > timedelta(days=14):
            return RateOutcome.UNAVAILABLE
        booking.rating = rating
        booking.rated_at = now
        await self.session.flush()
        await recompute_barber_rating(self.session, booking.barber_id)
        await self.session.commit()
        return RateOutcome.OK

    async def link_staff(
        self, token: str, chat_id: int, tg: TelegramUser, now: datetime
    ) -> Barber | None:
        barber_id = parse_token(
            token,
            self.settings.jwt_secret.get_secret_value(),
            now,
            timedelta(seconds=self.settings.staff_link_ttl_seconds),
        )
        if barber_id is None:
            return None
        barber = await self.session.get(Barber, barber_id)
        if barber is None:
            return None
        user = await self.registry.upsert_user(tg)
        before = barber.telegram_chat_id
        barber.telegram_chat_id = chat_id
        account = await self.session.scalar(
            select(AdminUser).where(AdminUser.barber_id == barber.id)
        )
        if account is not None and account.user_id is None:
            account.user_id = user.id
        self.audit.record(
            Actor.system(),
            "barber.telegram_link",
            "barber",
            barber.id,
            before={"telegram_chat_id": before},
            after={"telegram_chat_id": chat_id},
        )
        await self.session.commit()
        return barber

    @staticmethod
    def is_staff_link(args: str | None) -> bool:
        return bool(args and args.startswith(STAFF_PREFIX))

    async def confirm_visit(
        self, telegram_id: int, booking_id: uuid.UUID, now: datetime
    ) -> VisitOutcome:
        """'I'll come' from a reminder: marks the booking, the admin calendar shows a check."""
        found = await self._client_of(telegram_id)
        if found is None:
            return VisitOutcome.UNAVAILABLE
        client, _ = found
        booking = await self.session.scalar(
            select(Booking)
            .where(Booking.id == booking_id, Booking.client_id == client.id)
            .with_for_update()
        )
        if booking is None or booking.status not in ACTIVE_BOOKING_STATUSES:
            return VisitOutcome.UNAVAILABLE
        if booking.client_confirmed_at is None:
            booking.client_confirmed_at = now
            self.audit.record(
                Actor(type=ActorType.CLIENT, id=client.id),
                "booking.client_confirm",
                "booking",
                booking.id,
                after={"client_confirmed_at": now.isoformat()},
            )
            await self.session.commit()
        return VisitOutcome.CONFIRMED

    async def cancel_visit(
        self, telegram_id: int, booking_id: uuid.UUID, now: datetime, redis: Redis
    ) -> VisitOutcome:
        """Cancel from a reminder: the same rules, refunds and notifications as the Mini App."""
        found = await self._client_of(telegram_id)
        if found is None:
            return VisitOutcome.UNAVAILABLE
        client, salon = found
        service = ClientBookingService(self.session, redis, SlotCache(redis))
        try:
            await service.cancel(
                salon.branch_id,
                client,
                Actor(type=ActorType.CLIENT, id=client.id),
                booking_id,
                "Отменено из напоминания в Telegram",
                now,
            )
        except ValidationAppError as exc:
            await self.session.rollback()
            return (
                VisitOutcome.TOO_LATE if exc.code == "cancel_too_late" else VisitOutcome.UNAVAILABLE
            )
        except AppError:
            await self.session.rollback()
            return VisitOutcome.UNAVAILABLE
        return VisitOutcome.CANCELLED

    async def unsubscribe(self, telegram_id: int) -> bool:
        found = await self._client_of(telegram_id)
        if found is None:
            return False
        client, _ = found
        if not client.marketing_opt_out:
            client.marketing_opt_out = True
            self.audit.record(
                Actor(type=ActorType.CLIENT, id=client.id),
                "client.unsubscribe",
                "client",
                client.id,
                after={"marketing_opt_out": True},
            )
            await self.session.commit()
        return True
