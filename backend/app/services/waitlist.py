"""Waitlist: a client asks to be told when a fully booked day frees up.

When a booking is cancelled, the oldest entries for that barber (or "any barber") and that
local date get one Telegram message each with a button straight into booking. Whoever books
first gets the slot — the message says so; entries are notified once and then done.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import get_settings
from app.core.errors import NotFoundError, ValidationAppError
from app.models import (
    Barber,
    Booking,
    Client,
    SalonSettings,
    TelegramOutbox,
    User,
    WaitlistEntry,
)
from app.services.events import format_when

MAX_ACTIVE_PER_CLIENT = 5
NOTIFY_PER_FREED_SLOT = 5


class WaitlistService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _active(self, today: date) -> list[ColumnElement[bool]]:
        return [WaitlistEntry.day >= today, WaitlistEntry.notified_at.is_(None)]

    async def join(
        self,
        client: Client,
        salon: SalonSettings,
        *,
        barber_id: uuid.UUID | None,
        day: date,
        service_ids: list[uuid.UUID],
        now: datetime,
    ) -> WaitlistEntry:
        today = now.astimezone(ZoneInfo(salon.timezone)).date()
        if not today <= day <= today + timedelta(days=salon.max_days_ahead):
            raise ValidationAppError("The date is outside the booking window", code="bad_date")
        if barber_id is not None:
            barber = await self.session.get(Barber, barber_id)
            if barber is None or barber.branch_id != client.branch_id or not barber.is_active:
                raise NotFoundError("Barber not found")
        existing = await self.session.scalar(
            select(WaitlistEntry).where(
                WaitlistEntry.client_id == client.id,
                WaitlistEntry.day == day,
                WaitlistEntry.barber_id.is_(None)
                if barber_id is None
                else WaitlistEntry.barber_id == barber_id,
                *self._active(today),
            )
        )
        if existing is not None:
            return existing
        count = await self.session.scalar(
            select(func.count())
            .select_from(WaitlistEntry)
            .where(WaitlistEntry.client_id == client.id, *self._active(today))
        )
        if (count or 0) >= MAX_ACTIVE_PER_CLIENT:
            raise ValidationAppError(
                f"Up to {MAX_ACTIVE_PER_CLIENT} waitlist requests at a time", code="waitlist_full"
            )
        entry = WaitlistEntry(
            branch_id=client.branch_id,
            client_id=client.id,
            barber_id=barber_id,
            day=day,
            service_ids=[str(item) for item in service_ids],
        )
        self.session.add(entry)
        await self.session.commit()
        return entry

    async def active(
        self, client: Client, salon: SalonSettings, now: datetime
    ) -> list[WaitlistEntry]:
        today = now.astimezone(ZoneInfo(salon.timezone)).date()
        rows = await self.session.execute(
            select(WaitlistEntry)
            .where(WaitlistEntry.client_id == client.id, *self._active(today))
            .order_by(WaitlistEntry.day)
        )
        return list(rows.scalars())

    async def leave(self, client: Client, entry_id: uuid.UUID) -> None:
        entry = await self.session.get(WaitlistEntry, entry_id)
        if entry is None or entry.client_id != client.id:
            raise NotFoundError("Waitlist entry not found")
        await self.session.delete(entry)
        await self.session.commit()

    async def on_slot_freed(self, booking: Booking, salon: SalonSettings, now: datetime) -> int:
        """Queue messages to the oldest waiting clients for the freed barber/date. The caller
        commits (this runs inside the cancellation's transaction)."""
        tz = ZoneInfo(salon.timezone)
        day = booking.start_at.astimezone(tz).date()
        if booking.start_at <= now:
            return 0
        conditions = [
            WaitlistEntry.branch_id == booking.branch_id,
            WaitlistEntry.day == day,
            WaitlistEntry.notified_at.is_(None),
            or_(WaitlistEntry.barber_id.is_(None), WaitlistEntry.barber_id == booking.barber_id),
            User.bot_blocked.is_(False),
            Client.is_blocked.is_(False),
        ]
        if booking.client_id is not None:  # the one who cancelled does not need a message
            conditions.append(WaitlistEntry.client_id != booking.client_id)
        rows = (
            await self.session.execute(
                select(WaitlistEntry, Client, User)
                .join(Client, Client.id == WaitlistEntry.client_id)
                .join(User, User.id == Client.user_id)
                .where(*conditions)
                .order_by(WaitlistEntry.created_at)
                .limit(NOTIFY_PER_FREED_SLOT)
                .with_for_update(of=WaitlistEntry, skip_locked=True)
            )
        ).all()
        if not rows:
            return 0
        barber = await self.session.get(Barber, booking.barber_id)
        settings = get_settings()
        for entry, client, user in rows:
            entry.notified_at = now
            param = f"barber_{booking.barber_id}" if entry.barber_id else "book"
            if settings.miniapp_url:
                url = f"{settings.miniapp_url}?startapp={param}"
                button = {"text": _book_label(client.language), "web_app": url}
            else:
                link = f"https://t.me/{settings.bot_username}/{settings.miniapp_short_name}"
                button = {"text": _book_label(client.language), "url": f"{link}?startapp={param}"}
            self.session.add(
                TelegramOutbox(
                    chat_id=user.telegram_id,
                    template_key="waitlist_client",
                    language=client.language,
                    payload={
                        "barber": barber.name if barber else "",
                        "when": format_when(booking.start_at, tz),
                        "buttons": [[button]],
                    },
                    dedupe_key=f"waitlist:{entry.id}",
                )
            )
        return len(rows)


def _book_label(lang: str) -> str:
    from app.bot.texts import t  # local import: bot texts are not needed elsewhere here

    return t("revisit_book", lang)
