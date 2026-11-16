"""Marketing broadcasts to client segments.

Recipients always exclude clients who unsubscribed, were blocked by the salon, or blocked the
bot. Messages go through the outbox (retries, Telegram rate limits); rows are inserted with a
Core INSERT so a large broadcast is not drained inside the admin's HTTP request.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Select, exists, extract, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import NotFoundError, ValidationAppError
from app.models import Booking, Broadcast, Client, PromoCode, SalonSettings, TelegramOutbox, User
from app.models.enums import ACTIVE_BOOKING_STATUSES, BookingStatus
from app.services.audit import Actor, AuditService

SEGMENTS = ("all", "inactive", "never_visited", "birthday_month", "tag")
MAX_TEXT = 1000


@dataclass(frozen=True, slots=True)
class Segment:
    kind: str
    days: int | None = None
    tag: str | None = None

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> Segment:
        kind = str(raw.get("kind", ""))
        if kind not in SEGMENTS:
            raise ValidationAppError("Unknown segment", code="bad_segment")
        days = raw.get("days")
        if kind == "inactive" and not (isinstance(days, int) and 1 <= days <= 3650):
            raise ValidationAppError("Set the number of days", code="bad_segment")
        tag = (raw.get("tag") or "").strip() or None
        if kind == "tag" and not tag:
            raise ValidationAppError("Choose a tag", code="bad_segment")
        return cls(kind=kind, days=days if kind == "inactive" else None, tag=tag)


def recipients_query(
    branch_id: uuid.UUID, segment: Segment, salon: SalonSettings, now: datetime
) -> Select[Any]:
    """(client, telegram_id) of everyone in the segment who may receive marketing."""
    completed = select(Booking.id).where(
        Booking.client_id == Client.id, Booking.status == BookingStatus.COMPLETED
    )
    query = (
        select(Client, User.telegram_id)
        .join(User, User.id == Client.user_id)
        .where(
            Client.branch_id == branch_id,
            Client.is_blocked.is_(False),
            Client.marketing_opt_out.is_(False),
            User.bot_blocked.is_(False),
        )
    )
    if segment.kind == "inactive":
        last_visit = (
            select(func.max(Booking.start_at))
            .where(Booking.client_id == Client.id, Booking.status == BookingStatus.COMPLETED)
            .scalar_subquery()
        )
        upcoming = select(Booking.id).where(
            Booking.client_id == Client.id,
            Booking.status.in_(ACTIVE_BOOKING_STATUSES),
            Booking.start_at > now,
        )
        query = query.where(last_visit < now - timedelta(days=segment.days or 0), ~exists(upcoming))
    elif segment.kind == "never_visited":
        query = query.where(~exists(completed))
    elif segment.kind == "birthday_month":
        month = now.astimezone(ZoneInfo(salon.timezone)).month
        query = query.where(extract("month", Client.birthday) == month)
    elif segment.kind == "tag":
        query = query.where(Client.tags.contains([segment.tag]))
    return query


class BroadcastService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def count(self, salon: SalonSettings, segment: Segment, now: datetime) -> int:
        query = recipients_query(salon.branch_id, segment, salon, now).subquery()
        return int(await self.session.scalar(select(func.count()).select_from(query)) or 0)

    async def send(
        self,
        salon: SalonSettings,
        segment: Segment,
        texts: dict[str, str],
        promo_code_id: uuid.UUID | None,
        book_button: bool,
        actor: Actor,
        now: datetime,
    ) -> Broadcast:
        texts = {lang: text.strip() for lang, text in texts.items() if text and text.strip()}
        if "ru" not in texts:
            raise ValidationAppError("The Russian text is required", code="text_required")
        if any(len(text) > MAX_TEXT for text in texts.values()):
            raise ValidationAppError(f"Up to {MAX_TEXT} characters", code="text_too_long")
        promo: PromoCode | None = None
        if promo_code_id is not None:
            promo = await self.session.get(PromoCode, promo_code_id)
            if promo is None or promo.branch_id != salon.branch_id or not promo.is_active:
                raise NotFoundError("Promo code not found")

        broadcast = Broadcast(
            branch_id=salon.branch_id,
            created_by=actor.id,
            texts=texts,
            segment={"kind": segment.kind, "days": segment.days, "tag": segment.tag},
            promo_code_id=promo.id if promo else None,
        )
        self.session.add(broadcast)
        await self.session.flush()

        settings = get_settings()
        rows = (
            await self.session.execute(recipients_query(salon.branch_id, segment, salon, now))
        ).all()
        values = []
        for client, telegram_id in rows:
            lang = client.language if client.language in texts else "ru"
            buttons: list[list[dict[str, str]]] = []
            if book_button:
                buttons.append([_book_button(settings, lang)])
            buttons.append([{"text": _t("unsubscribe", lang), "callback_data": "unsub"}])
            values.append(
                {
                    "chat_id": telegram_id,
                    "template_key": "broadcast",
                    "language": lang,
                    "payload": {
                        "text": texts[lang],
                        "promo": f"\n\n🎁 {promo.code}" if promo else "",
                        "buttons": buttons,
                    },
                    "dedupe_key": f"broadcast:{broadcast.id}:{client.id}",
                }
            )
        for start in range(0, len(values), 500):
            await self.session.execute(
                insert(TelegramOutbox).values(values[start : start + 500]).on_conflict_do_nothing()
            )
        broadcast.recipients = len(values)
        AuditService(self.session).record(
            actor,
            "broadcast.send",
            "broadcast",
            broadcast.id,
            after={"segment": broadcast.segment, "recipients": len(values)},
        )
        await self.session.commit()
        return broadcast


def _t(key: str, lang: str) -> str:
    from app.bot.texts import t  # local import: keeps services free of bot imports at load

    return t(key, lang)


def _book_button(settings: Any, lang: str) -> dict[str, str]:
    label = _t("revisit_book", lang)
    if settings.miniapp_url:
        return {"text": label, "web_app": settings.miniapp_url}
    link = f"https://t.me/{settings.bot_username}/{settings.miniapp_short_name}?startapp=book"
    return {"text": label, "url": link}
