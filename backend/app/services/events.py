"""Booking events: admin feed rows, Telegram outbox and real-time publish.

`emit()` runs inside the business transaction (feed row and outbox commit or roll back with
the change). `publish()` is called after commit; losing it only delays the UI until the next
refetch, because the feed is persisted.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Barber,
    Booking,
    Client,
    Notification,
    SalonSettings,
    TelegramOutbox,
    User,
)
from app.models.enums import NotificationType
from app.notify.templates import format_money

logger = structlog.get_logger(__name__)

_OUTBOX_BASE = {
    NotificationType.BOOKING_CREATED: "booking_created",
    NotificationType.BOOKING_CANCELLED: "booking_cancelled",
    NotificationType.BOOKING_RESCHEDULED: "booking_rescheduled",
}


def channel(branch_id: uuid.UUID) -> str:
    return f"events:{branch_id}"


def format_when(instant: datetime, tz: ZoneInfo) -> str:
    return instant.astimezone(tz).strftime("%d.%m.%Y %H:%M")


class BookingEvents:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _client_user(self, client: Client | None) -> User | None:
        if client is None or client.user_id is None:
            return None
        return await self.session.get(User, client.user_id)

    def _values(
        self,
        booking: Booking,
        client: Client | None,
        barber: Barber,
        salon: SalonSettings,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        tz = ZoneInfo(salon.timezone)

        def money(amount: int) -> str:
            return format_money(amount, salon.currency)

        services = ", ".join(
            line.name_snapshot.get(salon.default_language) or line.name_snapshot.get("ru", "")
            for line in booking.services
        )
        values: dict[str, Any] = {
            "booking_id": str(booking.id),
            "barber_id": str(booking.barber_id),
            "client_id": str(client.id) if client else None,
            "when": format_when(booking.start_at, tz),
            "start_at": booking.start_at.isoformat(),
            "end_at": booking.end_at.isoformat(),
            "barber": barber.name,
            "client": client.name if client else "",
            "phone": client.phone if client and client.phone else "",
            "services": services,
            "subtotal": money(booking.subtotal),
            "bonus_spent": money(booking.bonus_spent),
            "bonus_spent_raw": booking.bonus_spent,
            "total_due": money(booking.total_due),
            "total_due_raw": booking.total_due,
            "source": booking.source.value,
            "status": booking.status.value,
            "salon": salon.name,
        }
        if "old_start_at" in extra:
            values["old_when"] = format_when(extra["old_start_at"], tz)
            values["old_start_at"] = extra["old_start_at"].isoformat()
        for key in ("cancelled_by", "reason"):
            if key in extra:
                values[key] = extra[key] or ""
        return values

    async def emit(
        self,
        event: NotificationType,
        booking: Booking,
        salon: SalonSettings,
        *,
        notify_client: bool = True,
        **extra: Any,
    ) -> Notification:
        client = await self.session.get(Client, booking.client_id) if booking.client_id else None
        barber = await self.session.get(Barber, booking.barber_id)
        if barber is None:  # pragma: no cover - FK guarantees it
            raise RuntimeError("barber missing")
        values = self._values(booking, client, barber, salon, extra)

        notification = Notification(
            branch_id=booking.branch_id,
            type=event,
            booking_id=booking.id,
            payload=values,
            created_at=datetime.now(UTC),
        )
        self.session.add(notification)

        base = _OUTBOX_BASE.get(event)
        if base is not None:
            user = await self._client_user(client)
            if notify_client and user is not None and not user.bot_blocked and client:
                self._outbox(user.telegram_id, f"{base}_client", client.language, values, booking)
            if salon.admin_chat_id:
                self._outbox(
                    salon.admin_chat_id, f"{base}_admin", salon.default_language, values, booking
                )
            if salon.notify_barbers and barber.telegram_chat_id:
                self._outbox(
                    barber.telegram_chat_id,
                    f"{base}_barber",
                    salon.default_language,
                    values,
                    booking,
                )
        await self.session.flush()
        return notification

    def _outbox(
        self,
        chat_id: int,
        template: str,
        language: str,
        values: dict[str, Any],
        booking: Booking,
    ) -> None:
        self.session.add(
            TelegramOutbox(
                chat_id=chat_id,
                template_key=template,
                language=language,
                payload=values,
                booking_id=booking.id,
            )
        )


RATING_DELAY = timedelta(hours=1)


async def request_rating(session: AsyncSession, booking: Booking, now: datetime) -> None:
    """Post-visit poll (1..5) an hour after completion; feeds the barber's rating."""
    if booking.client_id is None:
        return
    client = await session.get(Client, booking.client_id)
    if client is None or client.user_id is None:
        return
    user = await session.get(User, client.user_id)
    barber = await session.get(Barber, booking.barber_id)
    if user is None or user.bot_blocked or barber is None:
        return
    session.add(
        TelegramOutbox(
            chat_id=user.telegram_id,
            template_key="rate_visit_client",
            language=client.language,
            booking_id=booking.id,
            send_after=now + RATING_DELAY,
            dedupe_key=f"rate:{booking.id}",
            payload={
                "barber": barber.name,
                "buttons": [
                    [
                        {
                            "text": f"{value}⭐",
                            "callback_data": f"rate:{booking.id}:{value}",
                        }
                        for value in range(1, 6)
                    ]
                ],
            },
        )
    )


def event_message(notification: Notification) -> str:
    return json.dumps(
        {
            "id": str(notification.id),
            "type": notification.type.value,
            "booking_id": str(notification.booking_id) if notification.booking_id else None,
            "payload": notification.payload,
            "created_at": notification.created_at.isoformat() if notification.created_at else None,
        },
        ensure_ascii=False,
    )


async def publish(redis: Redis | None, notification: Notification) -> None:
    if redis is None:
        return
    try:
        await redis.publish(channel(notification.branch_id), event_message(notification))
    except RedisError:
        logger.warning("event_publish_failed", exc_info=True)
