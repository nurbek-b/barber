from __future__ import annotations

import itertools
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime, time, timedelta
from typing import Any

import httpx
import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageReplyMarkup,
    EditMessageText,
    SendMessage,
    SetChatMenuButton,
    SetMyCommands,
    SetWebhook,
    TelegramMethod,
)
from aiogram.types import Chat, Message
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.factory import create_bot
from app.bot.main import WEBHOOK_PATH, create_bot_app
from app.bot.setup import configure_bot
from app.core.config import Settings
from app.models import (
    AdminUser,
    Barber,
    Booking,
    BookingService,
    Branch,
    Client,
    TelegramOutbox,
    User,
)
from app.models.enums import AdminRole, BookingStatus, PaymentMethod
from app.services.staff_link import make_token, parse_token
from tests.conftest import AdminFactory, login_as

SECRET = "test-webhook-secret"
NOW = datetime.now(UTC)
_ids = itertools.count(1)


class MockedSession(BaseSession):
    """Records Bot API calls instead of sending them."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []

    async def make_request(
        self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None
    ) -> Any:
        self.calls.append(method)
        if isinstance(method, SendMessage | EditMessageText):
            chat_id = int(getattr(method, "chat_id", 0) or 0)
            return Message(
                message_id=next(_ids),
                date=NOW,
                chat=Chat(id=chat_id, type="private"),
                text=method.text,
            )
        return True

    async def close(self) -> None:
        return None

    async def stream_content(  # pragma: no cover - not used
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        yield b""

    def sent(self) -> list[SendMessage]:
        return [call for call in self.calls if isinstance(call, SendMessage)]


@pytest.fixture
def bot_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "miniapp_url": "https://barber.example/app/",
            "bot_username": "barber_test_bot",
        }
    )


@pytest.fixture
def tg() -> MockedSession:
    return MockedSession()


@pytest.fixture
async def bot_app(
    bot_settings: Settings, tg: MockedSession, branch: Branch
) -> AsyncIterator[FastAPI]:
    redis = FakeAsyncRedis(decode_responses=True)
    app = create_bot_app(bot_settings, redis=redis, bot=create_bot(bot_settings, session=tg))
    async with app.router.lifespan_context(app):
        yield app
    await redis.aclose()


@pytest.fixture
async def hook(bot_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=bot_app)
    async with httpx.AsyncClient(transport=transport, base_url="https://bot") as http:
        http.headers["X-Telegram-Bot-Api-Secret-Token"] = SECRET
        yield http


def tg_user(user_id: int = 100, lang: str = "ru") -> dict[str, Any]:
    return {"id": user_id, "is_bot": False, "first_name": "Бек", "language_code": lang}


def message(
    text: str | None = None,
    user_id: int = 100,
    chat_type: str = "private",
    chat_id: int | None = None,
    **extra: Any,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "message_id": next(_ids),
        "date": int(NOW.timestamp()),
        "chat": {"id": chat_id or user_id, "type": chat_type, "title": "Админы"}
        if chat_type != "private"
        else {"id": user_id, "type": "private"},
        "from": tg_user(user_id),
        **extra,
    }
    if text is not None:
        body["text"] = text
        if text.startswith("/"):
            body["entities"] = [
                {"type": "bot_command", "offset": 0, "length": len(text.split()[0])}
            ]
    return {"update_id": next(_ids), "message": body}


def callback(data: str, user_id: int = 100) -> dict[str, Any]:
    return {
        "update_id": next(_ids),
        "callback_query": {
            "id": str(next(_ids)),
            "from": tg_user(user_id),
            "chat_instance": "ci",
            "data": data,
            "message": {
                "message_id": next(_ids),
                "date": int(NOW.timestamp()),
                "chat": {"id": user_id, "type": "private"},
                "text": "poll",
            },
        },
    }


async def send(http: httpx.AsyncClient, update: dict[str, Any]) -> httpx.Response:
    response = await http.post(WEBHOOK_PATH, json=update)
    assert response.status_code == 200, response.text
    return response


async def client_of(session: AsyncSession, telegram_id: int) -> Client:
    client = await session.scalar(
        select(Client).join(User, User.id == Client.user_id).where(User.telegram_id == telegram_id)
    )
    assert client is not None
    return client


# ---------------------------------------------------------------------------
# webhook transport
# ---------------------------------------------------------------------------


async def test_secret_is_required(hook: httpx.AsyncClient, tg: MockedSession) -> None:
    for headers in ({"X-Telegram-Bot-Api-Secret-Token": "wrong"}, {}):
        hook.headers.pop("X-Telegram-Bot-Api-Secret-Token", None)
        hook.headers.update(headers)
        response = await hook.post(WEBHOOK_PATH, json=message("/start"))
        assert response.status_code == 401
    assert tg.calls == []


async def test_bad_payload(hook: httpx.AsyncClient) -> None:
    response = await hook.post(WEBHOOK_PATH, content=b"not json")
    assert response.status_code == 400


async def test_duplicate_update_is_ignored(hook: httpx.AsyncClient, tg: MockedSession) -> None:
    update = message("/help")
    await send(hook, update)
    second = await send(hook, update)
    assert second.json()["duplicate"] is True
    assert len(tg.sent()) == 1


# ---------------------------------------------------------------------------
# /start, contact, language, bookings
# ---------------------------------------------------------------------------


async def test_start_registers_client_and_shows_app_button(
    hook: httpx.AsyncClient, tg: MockedSession, session: AsyncSession
) -> None:
    await send(hook, message("/start"))
    welcome, ask_phone = tg.sent()
    assert "Test Barbershop" in welcome.text
    button = welcome.reply_markup.inline_keyboard[0][0]  # type: ignore[union-attr]
    assert button.web_app is not None
    assert button.web_app.url == "https://barber.example/app/"
    assert ask_phone.reply_markup.keyboard[0][0].request_contact is True  # type: ignore[union-attr]

    client = await client_of(session, 100)
    assert client.language == "ru"

    tg.calls.clear()
    await send(hook, message("/start"))
    assert len(tg.sent()) == 2  # still no phone → asks again; no second client
    assert len((await session.execute(select(Client))).scalars().all()) == 1


async def test_start_with_referral(hook: httpx.AsyncClient, session: AsyncSession) -> None:
    await send(hook, message("/start", user_id=200))
    referrer = await client_of(session, 200)
    await send(hook, message(f"/start ref_{referrer.referral_code}", user_id=201))
    invited = await client_of(session, 201)
    assert invited.referred_by_client_id == referrer.id


async def test_contact_saves_only_own_number(
    hook: httpx.AsyncClient, tg: MockedSession, session: AsyncSession
) -> None:
    await send(hook, message("/start"))
    tg.calls.clear()
    foreign = {"phone_number": "+996700000001", "first_name": "X", "user_id": 999}
    await send(hook, message(contact=foreign))
    assert "свой номер" in tg.sent()[0].text
    own = {"phone_number": "996 555 12 34 56", "first_name": "Бек", "user_id": 100}
    await send(hook, message(contact=own))
    client = await client_of(session, 100)
    await session.refresh(client)
    assert client.phone == "+996555123456"
    assert "+996555123456" in tg.sent()[1].text


async def test_language_switch(
    hook: httpx.AsyncClient, tg: MockedSession, session: AsyncSession
) -> None:
    await send(hook, message("/start"))
    await send(hook, message("/language"))
    await send(hook, callback("lang:ky"))
    client = await client_of(session, 100)
    await session.refresh(client)
    assert client.language == "ky"
    assert any(isinstance(call, AnswerCallbackQuery) for call in tg.calls)
    assert tg.sent()[-1].text == "Даяр, тил — кыргызча."


async def test_bookings_command(
    hook: httpx.AsyncClient, tg: MockedSession, session: AsyncSession, branch: Branch
) -> None:
    await send(hook, message("/start"))
    client = await client_of(session, 100)
    barber = Barber(branch_id=branch.id, name="Азамат")
    session.add(barber)
    await session.flush()
    start = NOW + timedelta(days=1)
    session.add(
        Booking(
            branch_id=branch.id,
            client_id=client.id,
            barber_id=barber.id,
            start_at=start,
            end_at=start + timedelta(hours=1),
            blocked_until=start + timedelta(hours=1),
            subtotal=1,
            bonus_spent=0,
            total_due=1,
        )
    )
    await session.commit()
    tg.calls.clear()
    await send(hook, message("/bookings"))
    text = tg.sent()[0].text
    assert "Азамат" in text
    assert "Ваши записи" in text


async def test_fallback_and_chatid(hook: httpx.AsyncClient, tg: MockedSession) -> None:
    await send(hook, message("привет"))
    assert "/bookings" in tg.sent()[0].text
    await send(hook, message("/chatid", user_id=100, chat_type="supergroup", chat_id=-100555))
    assert "-100555" in tg.sent()[1].text


async def test_user_blocks_bot(hook: httpx.AsyncClient, session: AsyncSession) -> None:
    await send(hook, message("/start"))
    bot_user = {"id": 123456, "is_bot": True, "first_name": "Bot"}
    update = {
        "update_id": next(_ids),
        "my_chat_member": {
            "chat": {"id": 100, "type": "private"},
            "from": tg_user(),
            "date": int(NOW.timestamp()),
            "old_chat_member": {"status": "member", "user": bot_user},
            "new_chat_member": {"status": "kicked", "user": bot_user, "until_date": 0},
        },
    }
    await send(hook, update)
    user = await session.scalar(select(User).where(User.telegram_id == 100))
    assert user is not None
    await session.refresh(user)
    assert user.bot_blocked is True
    await send(hook, message("/start"))  # writing again unblocks
    await session.refresh(user)
    assert user.bot_blocked is False


# ---------------------------------------------------------------------------
# barbers: link & rating
# ---------------------------------------------------------------------------


def test_staff_token() -> None:
    barber_id = uuid.uuid4()
    token = make_token(barber_id, "s" * 40, NOW)
    assert len(token) <= 64
    assert parse_token(token, "s" * 40, NOW, timedelta(days=7)) == barber_id
    assert parse_token(token, "x" * 40, NOW, timedelta(days=7)) is None
    assert parse_token(token, "s" * 40, NOW + timedelta(days=8), timedelta(days=7)) is None
    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
    assert parse_token(tampered, "s" * 40, NOW, timedelta(days=7)) is None
    assert parse_token("b_short", "s" * 40, NOW, timedelta(days=7)) is None


async def test_staff_link_flow(
    hook: httpx.AsyncClient,
    tg: MockedSession,
    session: AsyncSession,
    branch: Branch,
    client: httpx.AsyncClient,
    make_admin: AdminFactory,
) -> None:
    barber = Barber(branch_id=branch.id, name="Азамат")
    session.add(barber)
    await session.commit()
    account = await make_admin(AdminRole.BARBER, barber_id=barber.id)

    owner = await login_as(client, await make_admin(AdminRole.OWNER))
    link = (await owner.get(f"/api/v1/admin/barbers/{barber.id}/telegram-link")).json()["link"]
    token = link.rsplit("start=", 1)[1]

    await send(hook, message(f"/start {token}", user_id=300))
    assert "Азамат" in tg.sent()[0].text
    await session.refresh(barber)
    assert barber.telegram_chat_id == 300
    linked = await session.get(AdminUser, account.id)
    assert linked is not None
    await session.refresh(linked)
    assert linked.user_id is not None

    await send(hook, message("/start b_" + "0" * 56, user_id=301))
    assert "недействительна" in tg.sent()[1].text


async def test_rating_poll(
    hook: httpx.AsyncClient, tg: MockedSession, session: AsyncSession, branch: Branch
) -> None:
    await send(hook, message("/start", user_id=400))
    await send(hook, message("/start", user_id=401))
    client = await client_of(session, 400)
    barber = Barber(branch_id=branch.id, name="Мастер")
    session.add(barber)
    await session.flush()
    start = NOW - timedelta(hours=3)
    booking = Booking(
        branch_id=branch.id,
        client_id=client.id,
        barber_id=barber.id,
        status=BookingStatus.COMPLETED,
        start_at=start,
        end_at=start + timedelta(hours=1),
        blocked_until=start + timedelta(hours=1),
        subtotal=1,
        bonus_spent=0,
        total_due=1,
        completed_at=start + timedelta(hours=1),
        services=[BookingService(name_snapshot={"ru": "С"}, duration_min=60, price=1)],
    )
    session.add(booking)
    await session.commit()
    tg.calls.clear()

    await send(hook, callback(f"rate:{booking.id}:4", user_id=401))  # someone else
    await send(hook, callback(f"rate:{booking.id}:5", user_id=400))
    await send(hook, callback(f"rate:{booking.id}:1", user_id=400))  # second attempt
    await session.refresh(booking)
    await session.refresh(barber)
    assert booking.rating == 5
    assert barber.rating_x100 == 500
    assert barber.rating_count == 1
    edits = [call for call in tg.calls if isinstance(call, EditMessageText)]
    assert len(edits) == 1
    assert "⭐⭐⭐⭐⭐" in (edits[0].text or "")
    answers = [c for c in tg.calls if isinstance(c, AnswerCallbackQuery)]
    assert [a.text for a in answers] == [
        "Этот визит нельзя оценить.",
        None,
        "Вы уже оценили этот визит.",
    ]


async def test_completion_schedules_rating_poll(
    session: AsyncSession, branch: Branch, owner_client: httpx.AsyncClient, app: FastAPI
) -> None:
    from app.api.deps import get_now
    from app.models import BarberSchedule, BarberService, Service

    user = User(telegram_id=500, first_name="К")
    service = Service(branch_id=branch.id, name_i18n={"ru": "С"}, duration_min=60, base_price=1)
    barber = Barber(branch_id=branch.id, name="Мастер")
    session.add_all([user, service, barber])
    await session.flush()
    session.add(BarberService(barber_id=barber.id, service_id=service.id))
    client = Client(
        branch_id=branch.id,
        user_id=user.id,
        name="К",
        referral_code="rate5000",
        phone="+996700500500",
    )
    session.add(client)
    await session.commit()
    del BarberSchedule

    start = datetime(2026, 12, 7, 6, 0, tzinfo=UTC)
    created = await owner_client.post(
        "/api/v1/admin/bookings",
        json={
            "client_id": str(client.id),
            "barber_id": str(barber.id),
            "service_ids": [str(service.id)],
            "start_at": start.isoformat(),
            "ignore_schedule": True,
        },
    )
    assert created.status_code == 201, created.text
    finished = start + timedelta(hours=1, minutes=5)
    app.dependency_overrides[get_now] = lambda: finished
    try:
        done = await owner_client.post(
            f"/api/v1/admin/bookings/{created.json()['id']}/status",
            json={
                "version": created.json()["version"],
                "status": "completed",
                "payment_method": "cash",
            },
        )
    finally:
        app.dependency_overrides.pop(get_now, None)
    assert done.status_code == 200, done.text
    poll = await session.scalar(
        select(TelegramOutbox).where(TelegramOutbox.template_key == "rate_visit_client")
    )
    assert poll is not None
    assert poll.chat_id == 500
    assert poll.send_after == finished + timedelta(hours=1)
    buttons = poll.payload["buttons"][0]
    assert [b["callback_data"] for b in buttons] == [
        f"rate:{created.json()['id']}:{n}" for n in range(1, 6)
    ]


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------


async def test_configure_bot(bot_settings: Settings) -> None:
    session = MockedSession()
    bot = create_bot(bot_settings, session=session)
    report = await configure_bot(bot, bot_settings, "https://barber.example/")
    assert report.webhook_url == "https://barber.example/api/v1/bot/webhook"
    webhook = next(c for c in session.calls if isinstance(c, SetWebhook))
    assert webhook.secret_token == SECRET
    assert webhook.allowed_updates == ["message", "callback_query", "my_chat_member"]
    assert len([c for c in session.calls if isinstance(c, SetMyCommands)]) == 3
    menu = next(c for c in session.calls if isinstance(c, SetChatMenuButton))
    assert menu.menu_button.web_app.url == "https://barber.example/app/"  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="https"):
        await configure_bot(bot, bot_settings, "http://insecure")


# reminder buttons: "I'll come" / two-step cancel
# ---------------------------------------------------------------------------


async def _upcoming(session: AsyncSession, branch: Branch, client: Client, hours: float) -> Booking:
    barber = Barber(branch_id=branch.id, name="Мастер")
    session.add(barber)
    await session.flush()
    start = NOW + timedelta(hours=hours)
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
        services=[BookingService(name_snapshot={"ru": "С"}, duration_min=60, price=1)],
    )
    session.add(booking)
    await session.commit()
    return booking


async def test_reminder_confirm_and_cancel(
    hook: httpx.AsyncClient, tg: MockedSession, session: AsyncSession, branch: Branch
) -> None:
    await send(hook, message("/start", user_id=600))
    await send(hook, message("/start", user_id=601))
    client = await client_of(session, 600)
    first = await _upcoming(session, branch, client, hours=24)
    second = await _upcoming(session, branch, client, hours=48)
    late = await _upcoming(session, branch, client, hours=1)
    tg.calls.clear()

    # someone else's booking
    await send(hook, callback(f"visit:ok:{first.id}", user_id=601))
    await send(hook, callback(f"visit:ok:{first.id}", user_id=600))
    await session.refresh(first)
    assert first.client_confirmed_at is not None
    edits = [call for call in tg.calls if isinstance(call, EditMessageText)]
    assert edits[-1].text is not None
    assert "Спасибо, ждём вас" in edits[-1].text
    assert edits[-1].reply_markup is None

    # cancel is two-step: the first tap only swaps the buttons
    tg.calls.clear()
    await send(hook, callback(f"visit:ask:{second.id}", user_id=600))
    await session.refresh(second)
    assert second.status is BookingStatus.CONFIRMED
    swapped = [call for call in tg.calls if isinstance(call, EditMessageReplyMarkup)]
    assert swapped
    labels = [b.callback_data for row in swapped[0].reply_markup.inline_keyboard for b in row]  # type: ignore[union-attr]
    assert labels == [f"visit:cancel:{second.id}", f"visit:keep:{second.id}"]

    await send(hook, callback(f"visit:cancel:{second.id}", user_id=600))
    await session.refresh(second)
    assert second.status is BookingStatus.CANCELLED
    assert second.cancel_reason == "Отменено из напоминания в Telegram"
    edits = [call for call in tg.calls if isinstance(call, EditMessageText)]
    assert "Запись отменена" in (edits[-1].text or "")

    # too late to cancel online: the booking stays, the client is told to call
    tg.calls.clear()
    await send(hook, callback(f"visit:cancel:{late.id}", user_id=600))
    await session.refresh(late)
    assert late.status is BookingStatus.CONFIRMED
    answers = [c for c in tg.calls if isinstance(c, AnswerCallbackQuery)]
    assert answers[0].text is not None
    assert "позвоните" in answers[0].text
    assert answers[0].show_alert is True

    # "No, I'll come" after asking confirms the visit
    await send(hook, callback(f"visit:keep:{late.id}", user_id=600))
    await session.refresh(late)
    assert late.client_confirmed_at is not None


# barber side: /today and finishing a visit from Telegram
# ---------------------------------------------------------------------------


async def test_barber_today_and_finish(
    hook: httpx.AsyncClient,
    tg: MockedSession,
    session: AsyncSession,
    branch: Branch,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # midday in Bishkek: the visits below must fall on the same local day at any wall time
    now = datetime.combine(NOW.date(), time(6, 0), tzinfo=UTC)
    monkeypatch.setattr("app.bot.handlers._now", lambda: now)
    await send(hook, message("/start", user_id=800))  # a client
    client = await client_of(session, 800)
    client.name = "Айбек Асанов"
    barber = Barber(branch_id=branch.id, name="Мастер", telegram_chat_id=700)
    other = Barber(branch_id=branch.id, name="Другой", telegram_chat_id=701)
    session.add_all([barber, other])
    await session.flush()

    def visit(who: Barber, minutes: int) -> Booking:
        start = now + timedelta(minutes=minutes)
        return Booking(
            branch_id=branch.id,
            client_id=client.id,
            barber_id=who.id,
            status=BookingStatus.CONFIRMED,
            start_at=start,
            end_at=start + timedelta(minutes=30),
            blocked_until=start + timedelta(minutes=30),
            subtotal=50_000,
            bonus_spent=0,
            total_due=50_000,
            services=[BookingService(name_snapshot={"ru": "Стрижка"}, duration_min=30, price=1)],
        )

    started, later, foreign = visit(barber, -5), visit(barber, 40), visit(other, -5)
    session.add_all([started, later, foreign])
    await session.commit()
    tg.calls.clear()

    await send(hook, message("/today", user_id=900))  # not a barber
    assert "для мастеров" in (tg.sent()[-1].text or "")

    await send(hook, message("/today", user_id=700))
    reply = tg.sent()[-1]
    assert "записей: 2" in (reply.text or "")
    assert "<b>Айбек Асанов</b>" in (reply.text or "")
    buttons = [b.callback_data for row in reply.reply_markup.inline_keyboard for b in row]  # type: ignore[union-attr]
    assert buttons == [f"done:{started.id}"], "only visits that have started"

    await send(hook, callback(f"done:{started.id}", user_id=700))
    methods = [c for c in tg.calls if isinstance(c, EditMessageReplyMarkup)][-1]
    data = [b.callback_data for row in methods.reply_markup.inline_keyboard for b in row]  # type: ignore[union-attr]
    assert data[:3] == [f"done:{started.id}:{m}" for m in ("cash", "card", "transfer")]

    await send(hook, callback(f"done:{started.id}:card", user_id=700))
    await session.refresh(started)
    assert started.status is BookingStatus.COMPLETED
    assert started.payment_method is PaymentMethod.CARD
    assert started.paid_amount == 50_000
    answers = [c for c in tg.calls if isinstance(c, AnswerCallbackQuery)]
    assert "Завершено" in (answers[-1].text or "")

    # someone else's visit cannot be finished
    await send(hook, callback(f"done:{foreign.id}:cash", user_id=700))
    await session.refresh(foreign)
    assert foreign.status is BookingStatus.CONFIRMED
    answers = [c for c in tg.calls if isinstance(c, AnswerCallbackQuery)]
    assert answers[-1].show_alert is True


async def test_unsubscribe_button(
    hook: httpx.AsyncClient, tg: MockedSession, session: AsyncSession
) -> None:
    await send(hook, message("/start", user_id=950))
    tg.calls.clear()
    await send(hook, callback("unsub", user_id=950))
    client = await client_of(session, 950)
    await session.refresh(client)
    assert client.marketing_opt_out is True
    answers = [c for c in tg.calls if isinstance(c, AnswerCallbackQuery)]
    assert "отписались" in (answers[0].text or "")
