from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models import (
    Barber,
    Booking,
    BookingService,
    Branch,
    Client,
    SalonSettings,
    TelegramOutbox,
    User,
)
from app.models.enums import BookingStatus, OutboxStatus
from app.notify.templates import format_money, render
from app.worker.barber_digest import send_barber_digests
from app.worker.outbox import (
    MAX_ATTEMPTS,
    RecipientBlockedError,
    RetryAfterError,
    SendError,
    drain_outbox,
)
from app.worker.reminders import scan_reminders
from app.worker.revisits import scan_revisits

TZ = ZoneInfo("Asia/Bishkek")
NOW = datetime(2026, 12, 7, 4, 0, tzinfo=UTC)  # 10:00 Bishkek


class FakeSender:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.buttons: list[list[list[dict[str, Any]]] | None] = []
        self.fail_with: dict[int, Exception] = {}

    async def send(
        self, chat_id: int, text: str, buttons: list[list[dict[str, Any]]] | None = None
    ) -> None:
        if chat_id in self.fail_with:
            raise self.fail_with[chat_id]
        self.sent.append((chat_id, text))
        self.buttons.append(buttons)


# ---------------------------------------------------------------------------
# templates
# ---------------------------------------------------------------------------


def test_format_money() -> None:
    assert format_money(150_000, "KGS") == "1 500 сом"
    assert format_money(150_050, "KGS") == "1 500,50 сом"
    assert format_money(0, "KGS") == "0 сом"


def test_render_escapes_html_and_falls_back() -> None:
    values = {
        "when": "07.12 12:00",
        "barber": "<b>Hack</b>",
        "services": "A & B",
        "total_due": "1 500 сом",
        "salon": "S",
        "bonus_spent_raw": 0,
    }
    text = render("booking_created_client", "ky", values)
    assert "&lt;b&gt;Hack&lt;/b&gt;" in text
    assert "A &amp; B" in text
    assert text.startswith("✅ <b>Сиз жазылдыңыз</b>")
    assert "бонус" not in text
    # unknown language → ru
    assert render("booking_created_client", "de", values).startswith("✅ <b>Вы записаны</b>")


def test_render_salon_override_and_broken_override() -> None:
    values = {"when": "07.12 12:00"}
    overrides = {"booking_cancelled_client": {"ru": "Отмена {when}!"}}
    assert render("booking_cancelled_client", "ru", values, overrides) == "Отмена 07.12 12:00!"
    broken = {"booking_cancelled_client": {"ru": "Отмена {when"}}
    assert "07.12 12:00" in render("booking_cancelled_client", "ru", values, broken)
    with pytest.raises(KeyError):
        render("no_such_template", "ru", values)


# ---------------------------------------------------------------------------
# outbox
# ---------------------------------------------------------------------------


async def _outbox(session: AsyncSession, chat_id: int, **kwargs: object) -> TelegramOutbox:
    values: dict[str, object] = {
        "chat_id": chat_id,
        "template_key": "booking_cancelled_client",
        "language": "ru",
        "payload": {"when": "07.12.2026 12:00"},
        "send_after": NOW - timedelta(seconds=1),
        **kwargs,
    }
    row = TelegramOutbox(**values)
    session.add(row)
    await session.commit()
    return row


async def test_outbox_sends_and_marks(
    maker: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    row = await _outbox(session, 1)
    future = await _outbox(session, 2, send_after=NOW + timedelta(minutes=5))
    sender = FakeSender()
    stats = await drain_outbox(maker, sender, NOW)
    assert stats.sent == 1
    assert sender.sent == [(1, "❌ Запись на 07.12.2026 12:00 отменена.")]
    await session.refresh(row)
    await session.refresh(future)
    assert row.status is OutboxStatus.SENT
    assert future.status is OutboxStatus.PENDING
    assert (await drain_outbox(maker, sender, NOW)).sent == 0, "never sent twice"


async def test_outbox_retry_backoff_and_dead_letter(
    maker: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    row = await _outbox(session, 5)
    sender = FakeSender()
    sender.fail_with[5] = SendError("network")
    now = NOW
    for _attempt in range(MAX_ATTEMPTS):
        await drain_outbox(maker, sender, now)
        await session.refresh(row)
        now = row.send_after + timedelta(seconds=1)
    assert row.status is OutboxStatus.DEAD
    assert row.attempts == MAX_ATTEMPTS


async def test_outbox_retry_after_pauses_batch(
    maker: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    first = await _outbox(session, 7)
    await _outbox(session, 8)
    sender = FakeSender()
    sender.fail_with[7] = RetryAfterError(30)
    stats = await drain_outbox(maker, sender, NOW)
    assert stats.sent == 0
    await session.refresh(first)
    assert first.attempts == 0
    assert first.send_after == NOW + timedelta(seconds=30)


async def test_outbox_blocked_user(
    maker: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    user = User(telegram_id=9, first_name="X")
    session.add(user)
    await session.commit()
    row = await _outbox(session, 9)
    sender = FakeSender()
    sender.fail_with[9] = RecipientBlockedError("Forbidden: bot was blocked by the user")
    await drain_outbox(maker, sender, NOW)
    await session.refresh(row)
    await session.refresh(user)
    assert row.status is OutboxStatus.DEAD
    assert user.bot_blocked is True


# ---------------------------------------------------------------------------
# reminders
# ---------------------------------------------------------------------------


async def _booking(
    session: AsyncSession, branch: Branch, start: datetime, created: datetime, telegram_id: int
) -> Booking:
    user = User(telegram_id=telegram_id, first_name="Клиент")
    barber = Barber(branch_id=branch.id, name="Мастер")
    session.add_all([user, barber])
    await session.flush()
    client = Client(
        branch_id=branch.id,
        user_id=user.id,
        name="Клиент",
        referral_code=f"r{telegram_id}",
        language="ky",
    )
    session.add(client)
    await session.flush()
    booking = Booking(
        branch_id=branch.id,
        client_id=client.id,
        barber_id=barber.id,
        status=BookingStatus.CONFIRMED,
        start_at=start,
        end_at=start + timedelta(hours=1),
        blocked_until=start + timedelta(hours=1),
        subtotal=1,
        bonus_spent=0,
        total_due=1,
        created_at=created,
        services=[
            BookingService(
                name_snapshot={"ru": "Стрижка", "ky": "Чач кырктыруу"}, duration_min=60, price=1
            )
        ],
    )
    session.add(booking)
    await session.commit()
    return booking


async def _reminders(session: AsyncSession) -> list[TelegramOutbox]:
    rows = await session.execute(
        select(TelegramOutbox).where(TelegramOutbox.template_key == "reminder_client")
    )
    return list(rows.scalars())


async def test_reminders_24h_and_2h(
    maker: async_sessionmaker[AsyncSession], session: AsyncSession, branch: Branch
) -> None:
    start = datetime.combine(date(2026, 12, 8), time(12), tzinfo=TZ).astimezone(UTC)
    await _booking(session, branch, start, created=start - timedelta(days=3), telegram_id=111)

    assert await scan_reminders(maker, start - timedelta(hours=25)) == 0
    assert await scan_reminders(maker, start - timedelta(hours=23, minutes=59)) == 1
    assert await scan_reminders(maker, start - timedelta(hours=23)) == 0, "only once"
    assert await scan_reminders(maker, start - timedelta(hours=1, minutes=59)) == 1
    assert await scan_reminders(maker, start - timedelta(minutes=30)) == 0

    rows = await _reminders(session)
    assert sorted(row.payload["offset_min"] for row in rows) == [120, 1440]
    assert all(row.chat_id == 111 and row.language == "ky" for row in rows)
    assert rows[0].payload["services"] == "Чач кырктыруу"
    assert rows[0].payload["when"] == "08.12.2026 12:00"


async def test_late_booking_gets_only_relevant_reminder(
    maker: async_sessionmaker[AsyncSession], session: AsyncSession, branch: Branch
) -> None:
    start = NOW + timedelta(hours=5)
    await _booking(session, branch, start, created=NOW, telegram_id=222)
    assert await scan_reminders(maker, NOW + timedelta(minutes=1)) == 0  # no 24 h reminder
    assert await scan_reminders(maker, start - timedelta(hours=2)) == 1
    assert [row.payload["offset_min"] for row in await _reminders(session)] == [120]


async def test_worker_downtime_sends_single_nearest_reminder(
    maker: async_sessionmaker[AsyncSession], session: AsyncSession, branch: Branch
) -> None:
    start = NOW + timedelta(days=3)
    await _booking(session, branch, start, created=NOW, telegram_id=333)
    # worker was down until 1 hour before the visit: both moments passed
    assert await scan_reminders(maker, start - timedelta(hours=1)) == 1
    assert await scan_reminders(maker, start - timedelta(minutes=59)) == 0
    assert [row.payload["offset_min"] for row in await _reminders(session)] == [120]


async def test_cancelled_and_blocked_get_no_reminders(
    maker: async_sessionmaker[AsyncSession], session: AsyncSession, branch: Branch
) -> None:
    start = NOW + timedelta(hours=10)
    cancelled = await _booking(
        session, branch, start, created=NOW - timedelta(days=2), telegram_id=444
    )
    cancelled.status = BookingStatus.CANCELLED
    blocked = await _booking(
        session, branch, start, created=NOW - timedelta(days=2), telegram_id=555
    )
    user = await session.scalar(select(User).where(User.telegram_id == 555))
    assert user is not None
    user.bot_blocked = True
    await session.commit()
    assert blocked.id
    assert await scan_reminders(maker, NOW) == 0


async def test_no_offsets_configured(
    maker: async_sessionmaker[AsyncSession], session: AsyncSession, branch: Branch
) -> None:
    salon = await session.get(SalonSettings, branch.id)
    assert salon is not None
    salon.reminder_offsets_min = []
    await session.commit()
    start = NOW + timedelta(hours=1)
    await _booking(session, branch, start, created=NOW - timedelta(days=1), telegram_id=666)
    assert await scan_reminders(maker, NOW) == 0


async def test_outbox_passes_buttons(
    maker: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    buttons = [[{"text": "5⭐", "callback_data": "rate:x:5"}]]
    await _outbox(session, 11, payload={"when": "x", "buttons": buttons})
    sender = FakeSender()
    await drain_outbox(maker, sender, NOW)
    assert sender.buttons == [buttons]


async def test_reminder_buttons(
    maker: async_sessionmaker[AsyncSession], session: AsyncSession, branch: Branch
) -> None:
    start = datetime.combine(date(2026, 12, 8), time(12), tzinfo=TZ).astimezone(UTC)
    booking = await _booking(
        session, branch, start, created=start - timedelta(days=3), telegram_id=121
    )
    await scan_reminders(maker, start - timedelta(hours=23, minutes=59))
    await scan_reminders(maker, start - timedelta(hours=1, minutes=59))
    rows = sorted(await _reminders(session), key=lambda row: -row.payload["offset_min"])
    day_before, two_hours = (row.payload["buttons"] for row in rows)
    # 24 h: confirm + cancel (client language: ky)
    assert [b["callback_data"] for b in day_before[0]] == [
        f"visit:ok:{booking.id}",
        f"visit:ask:{booking.id}",
    ]
    assert day_before[0][0]["text"] == "✅ Келем"
    # 2 h: online cancelling closed (cancel_min_hours = 2) -> only confirm
    assert [b["callback_data"] for b in two_hours[0]] == [f"visit:ok:{booking.id}"]


# "time for a haircut"
# ---------------------------------------------------------------------------


async def _visit(
    session: AsyncSession,
    branch: Branch,
    telegram_id: int,
    days_ago: int,
    *,
    upcoming: bool = False,
) -> Booking:
    now = datetime.now(UTC)
    old = await _booking(
        session,
        branch,
        now - timedelta(days=days_ago),
        created=now - timedelta(days=days_ago + 1),
        telegram_id=telegram_id,
    )
    old.status = BookingStatus.COMPLETED
    if upcoming:
        session.add(
            Booking(
                branch_id=branch.id,
                client_id=old.client_id,
                barber_id=old.barber_id,
                status=BookingStatus.CONFIRMED,
                start_at=now + timedelta(days=2),
                end_at=now + timedelta(days=2, hours=1),
                blocked_until=now + timedelta(days=2, hours=1),
                subtotal=1,
                bonus_spent=0,
                total_due=1,
            )
        )
    await session.commit()
    return old


def _local(hour: int) -> datetime:
    return datetime.combine(datetime.now(TZ).date(), time(hour), tzinfo=TZ).astimezone(UTC)


async def test_revisit_nudges(
    maker: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    branch: Branch,
    settings: Settings,
) -> None:
    due = await _visit(session, branch, 201, days_ago=31)
    await _visit(session, branch, 202, days_ago=31, upcoming=True)  # already booked again
    await _visit(session, branch, 203, days_ago=90)  # too old: no mass message on enable
    await _visit(session, branch, 204, days_ago=10)  # too early

    assert await scan_revisits(maker, settings, _local(22)) == 0, "quiet hours"
    assert await scan_revisits(maker, settings, _local(12)) == 1
    assert await scan_revisits(maker, settings, _local(13)) == 0, "once per visit"

    rows = (
        (
            await session.execute(
                select(TelegramOutbox).where(TelegramOutbox.template_key == "revisit_client")
            )
        )
        .scalars()
        .all()
    )
    assert [row.chat_id for row in rows] == [201]
    assert rows[0].booking_id == due.id
    assert rows[0].payload["days"] == 30
    assert rows[0].payload["buttons"][0][0]["text"] == "✂️ Жазылуу"
    text = render("revisit_client", "ru", rows[0].payload, None)
    assert "30 дн." in text


async def test_revisit_disabled(
    maker: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    branch: Branch,
    settings: Settings,
) -> None:
    await _visit(session, branch, 211, days_ago=31)
    salon = (await session.execute(select(SalonSettings))).scalar_one()
    salon.revisit_after_days = 0
    await session.commit()
    assert await scan_revisits(maker, settings, _local(12)) == 0


async def test_barber_morning_digest(
    maker: async_sessionmaker[AsyncSession], session: AsyncSession, branch: Branch
) -> None:
    day = datetime.now(TZ).date()
    at = lambda hour: datetime.combine(day, time(hour), tzinfo=TZ).astimezone(UTC)  # noqa: E731
    booking = await _booking(session, branch, at(14), created=at(8), telegram_id=131)
    barber = await session.get(Barber, booking.barber_id)
    assert barber is not None
    barber.telegram_chat_id = 7001
    lonely = Barber(branch_id=branch.id, name="Свободный", telegram_chat_id=7002)
    session.add(lonely)
    await session.commit()

    assert await send_barber_digests(maker, at(8)) == 0, "only at 9:00"
    assert await send_barber_digests(maker, at(9)) == 1, "barbers without bookings get nothing"
    assert await send_barber_digests(maker, at(9)) == 0, "once a day"

    row = (
        await session.execute(
            select(TelegramOutbox).where(TelegramOutbox.template_key == "barber_morning")
        )
    ).scalar_one()
    assert row.chat_id == 7001
    text = render(row.template_key, row.language, row.payload, None)
    assert "14:00–15:00 • Клиент · Стрижка" in text
    assert "/today" in text
