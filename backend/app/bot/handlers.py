from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import ChatMemberUpdatedFilter, Command, CommandObject, CommandStart
from aiogram.filters.chat_member_updated import KICKED, MEMBER
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
)
from aiogram.types import User as TgUser
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards
from app.bot.texts import t
from app.core.config import Settings
from app.core.errors import AppError
from app.core.security.initdata import TelegramUser
from app.models.enums import PaymentMethod
from app.services.barber_bot import Agenda, BarberBot
from app.services.bot_actions import BotActions, RateOutcome, VisitOutcome
from app.services.branches import BranchNotConfiguredError, BranchService
from app.services.events import format_when

private = F.chat.type == ChatType.PRIVATE


def _tg(user: TgUser) -> TelegramUser:
    return TelegramUser(
        id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        language_code=user.language_code,
        is_premium=bool(user.is_premium),
    )


def _now() -> datetime:
    return datetime.now(UTC)


async def start(
    message: Message, command: CommandObject, session: AsyncSession, settings: Settings
) -> None:
    if message.from_user is None:
        return
    actions = BotActions(session, settings)
    args = command.args
    if BotActions.is_staff_link(args):
        assert args is not None  # noqa: S101 - checked above
        barber = await actions.link_staff(args, message.chat.id, _tg(message.from_user), _now())
        lang = message.from_user.language_code
        if barber is None:
            await message.answer(t("staff_link_invalid", lang))
        else:
            await message.answer(t("staff_linked", lang, barber=barber.name))
        return

    try:
        result = await actions.start(_tg(message.from_user), args, _now())
    except BranchNotConfiguredError:
        return
    lang = result.client.language
    if result.client.is_blocked:
        await message.answer(t("blocked", lang))
        return
    text = t("welcome", lang, name=message.from_user.first_name, salon=result.salon.name)
    if result.welcome_bonus:
        text += "\n\n" + t("welcome_bonus", lang)
    await message.answer(text, reply_markup=keyboards.open_app(settings, lang))
    if not result.client.phone:
        await message.answer(t("ask_phone", lang), reply_markup=keyboards.share_phone(lang))


async def contact(message: Message, session: AsyncSession, settings: Settings) -> None:
    if message.from_user is None or message.contact is None:
        return
    actions = BotActions(session, settings)
    lang = await actions.language_of(message.from_user.id, message.from_user.language_code)
    if message.contact.user_id != message.from_user.id:
        await message.answer(t("phone_not_own", lang), reply_markup=keyboards.share_phone(lang))
        return
    phone = await actions.save_contact(message.from_user.id, message.contact.phone_number)
    if phone is None:
        await message.answer(t("phone_not_own", lang), reply_markup=keyboards.share_phone(lang))
        return
    await message.answer(t("phone_saved", lang, phone=phone), reply_markup=ReplyKeyboardRemove())
    await message.answer(t("help", lang), reply_markup=keyboards.open_app(settings, lang))


async def bookings(message: Message, session: AsyncSession, settings: Settings) -> None:
    if message.from_user is None:
        return
    actions = BotActions(session, settings)
    client, items, salon = await actions.upcoming(message.from_user.id, _now())
    lang = client.language if client else message.from_user.language_code or "ru"
    if not items or salon is None:
        await message.answer(
            t("no_bookings", lang), reply_markup=keyboards.open_app(settings, lang)
        )
        return
    tz = ZoneInfo(salon.timezone)
    lines = [t("bookings_header", lang)] + [
        t("booking_line", lang, when=format_when(booking.start_at, tz), barber=barber.name)
        for booking, barber in items
    ]
    await message.answer("\n".join(lines), reply_markup=keyboards.open_app(settings, lang))


async def language(message: Message) -> None:
    lang = message.from_user.language_code if message.from_user else None
    await message.answer(t("choose_language", lang), reply_markup=keyboards.languages())


async def language_chosen(
    callback: CallbackQuery, session: AsyncSession, settings: Settings
) -> None:
    code = (callback.data or "").removeprefix("lang:")
    changed = await BotActions(session, settings).set_language(callback.from_user.id, code)
    await callback.answer()
    if changed and callback.message is not None:
        await callback.message.answer(t("language_set", code))


async def rate(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    try:
        _, booking_raw, value_raw = (callback.data or "").split(":")
        booking_id, value = uuid.UUID(booking_raw), int(value_raw)
    except ValueError:
        await callback.answer()
        return
    actions = BotActions(session, settings)
    outcome = await actions.rate(callback.from_user.id, booking_id, value, _now())
    lang = await actions.language_of(callback.from_user.id, callback.from_user.language_code)
    if outcome is RateOutcome.OK:
        await callback.answer()
        if callback.message is not None:
            await callback.bot.edit_message_text(  # type: ignore[union-attr]
                text=t("rate_thanks", lang, stars="⭐" * value),
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                reply_markup=keyboards.write_review(settings, lang, booking_id),
            )
    elif outcome is RateOutcome.ALREADY:
        await callback.answer(t("rate_already", lang), show_alert=False)
    else:
        await callback.answer(t("rate_unavailable", lang), show_alert=False)


async def visit(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, redis: Redis | None = None
) -> None:
    """Reminder buttons: visit:ok / visit:ask (two-step cancel) / visit:keep / visit:cancel."""
    try:
        _, action, booking_raw = (callback.data or "").split(":")
        booking_id = uuid.UUID(booking_raw)
    except ValueError:
        await callback.answer()
        return
    actions = BotActions(session, settings)
    lang = await actions.language_of(callback.from_user.id, callback.from_user.language_code)
    message = callback.message if isinstance(callback.message, Message) else None

    if action == "ask":
        await callback.answer(t("visit_cancel_sure", lang))
        if message is not None:
            await message.edit_reply_markup(
                reply_markup=keyboards.cancel_confirmation(lang, booking_id)
            )
        return

    if action in ("ok", "keep"):
        outcome = await actions.confirm_visit(callback.from_user.id, booking_id, _now())
    elif action == "cancel" and redis is not None:
        outcome = await actions.cancel_visit(callback.from_user.id, booking_id, _now(), redis)
    else:
        await callback.answer()
        return

    if outcome is VisitOutcome.TOO_LATE:
        await callback.answer(t("visit_too_late", lang), show_alert=True)
        return
    if outcome is VisitOutcome.UNAVAILABLE:
        await callback.answer(t("visit_unavailable", lang), show_alert=False)
        if message is not None:
            await message.edit_reply_markup(reply_markup=None)
        return
    await callback.answer()
    if message is not None:
        key = "visit_confirmed" if outcome is VisitOutcome.CONFIRMED else "visit_cancelled"
        # keep the reminder text, drop the buttons, add the result line
        await message.edit_text(f"{message.html_text}\n\n{t(key, lang)}", reply_markup=None)


def _agenda_text(
    agenda: Agenda, lang: str, now: datetime
) -> tuple[str, InlineKeyboardMarkup | None]:
    day = agenda.day.strftime("%d.%m")
    if not agenda.items:
        return t("barber_day_empty", lang, date=day), None
    text = t("barber_day", lang, date=day, count=len(agenda.items)) + "\n\n" + agenda.lines(lang)
    finishable = agenda.finishable(now)
    if not finishable:
        return text, None
    return text + "\n\n" + t("barber_finish_hint", lang), keyboards.finish_visits(
        [
            (item.booking.id, item.booking.start_at.astimezone(agenda.tz), item.client_name)
            for item in finishable
        ]
    )


async def barber_day(
    message: Message, session: AsyncSession, settings: Settings, command: CommandObject
) -> None:
    """/today and /tomorrow for barbers linked through the staff link."""
    bot_barber = BarberBot(session)
    barber = await bot_barber.barber_of_chat(message.chat.id)
    lang = message.from_user.language_code if message.from_user else None
    if barber is None:
        await message.answer(t("barber_not_linked", lang))
        return
    salon_tz = ZoneInfo((await BranchService(session).settings(barber.branch_id)).timezone)
    now = _now()
    day = now.astimezone(salon_tz).date()
    if command.command == "tomorrow":
        day += timedelta(days=1)
    agenda = await bot_barber.agenda(barber, day)
    text, markup = _agenda_text(agenda, lang or agenda.salon.default_language, now)
    await message.answer(text, reply_markup=markup)


async def finish(
    callback: CallbackQuery, session: AsyncSession, settings: Settings, redis: Redis | None = None
) -> None:
    """done:<id> → payment buttons; done:<id>:<method> → finish; done:back → today's list."""
    parts = (callback.data or "").split(":")
    message = callback.message if isinstance(callback.message, Message) else None
    bot_barber = BarberBot(session)
    barber = await bot_barber.barber_of_chat(callback.from_user.id) if message else None
    lang = callback.from_user.language_code
    if barber is None or message is None:
        await callback.answer(t("barber_not_linked", lang), show_alert=True)
        return
    now = _now()
    salon_tz = ZoneInfo((await BranchService(session).settings(barber.branch_id)).timezone)
    if parts[1:] == ["back"]:
        agenda = await bot_barber.agenda(barber, now.astimezone(salon_tz).date())
        text, markup = _agenda_text(agenda, lang or agenda.salon.default_language, now)
        await callback.answer()
        await message.edit_text(text, reply_markup=markup)
        return
    try:
        booking_id = uuid.UUID(parts[1])
    except (IndexError, ValueError):
        await callback.answer()
        return
    if len(parts) == 2:
        await callback.answer(t("barber_pay_how", lang))
        await message.edit_reply_markup(reply_markup=keyboards.payment_methods(lang, booking_id))
        return
    try:
        method = PaymentMethod(parts[2])
        booking, amount = await bot_barber.complete(barber, booking_id, method, now, redis)
    except (ValueError, AppError):
        await session.rollback()
        await callback.answer(t("barber_cannot_finish", lang), show_alert=True)
        return
    agenda = await bot_barber.agenda(barber, now.astimezone(salon_tz).date())
    client = next((item.client_name for item in agenda.items if item.booking.id == booking.id), "")
    await callback.answer(
        t(
            "barber_done",
            lang,
            time=booking.start_at.astimezone(salon_tz).strftime("%H:%M"),
            client=client,
            amount=amount,
        )
    )
    text, markup = _agenda_text(agenda, lang or agenda.salon.default_language, now)
    await message.edit_text(text, reply_markup=markup)


async def chat_id(message: Message) -> None:
    """Add the bot to the admin group and send /chatid to learn its ID for the settings."""
    lang = message.from_user.language_code if message.from_user else None
    await message.answer(t("chat_id", lang, chat_id=message.chat.id))


async def bot_blocked(event: ChatMemberUpdated, session: AsyncSession, settings: Settings) -> None:
    if event.chat.type == ChatType.PRIVATE:
        await BotActions(session, settings).set_blocked(event.from_user.id, True)


async def bot_unblocked(
    event: ChatMemberUpdated, session: AsyncSession, settings: Settings
) -> None:
    if event.chat.type == ChatType.PRIVATE:
        await BotActions(session, settings).set_blocked(event.from_user.id, False)


async def fallback(message: Message, session: AsyncSession, settings: Settings) -> None:
    if message.from_user is None:
        return
    lang = await BotActions(session, settings).language_of(
        message.from_user.id, message.from_user.language_code
    )
    await message.answer(t("help", lang), reply_markup=keyboards.open_app(settings, lang))


def build_router() -> Router:
    """A fresh router per dispatcher (aiogram routers can be attached only once)."""
    router = Router(name="main")
    router.message.register(start, CommandStart(), private)
    router.message.register(contact, F.contact, private)
    router.message.register(bookings, Command("bookings"), private)
    router.message.register(language, Command("language"), private)
    router.callback_query.register(language_chosen, F.data.startswith("lang:"))
    router.callback_query.register(rate, F.data.startswith("rate:"))
    router.callback_query.register(visit, F.data.startswith("visit:"))
    router.callback_query.register(finish, F.data.startswith("done:"))
    router.message.register(chat_id, Command("chatid"))
    router.message.register(barber_day, Command("today", "tomorrow"), private)
    router.my_chat_member.register(
        bot_blocked, ChatMemberUpdatedFilter(member_status_changed=KICKED)
    )
    router.my_chat_member.register(
        bot_unblocked, ChatMemberUpdatedFilter(member_status_changed=MEMBER)
    )
    router.message.register(fallback, private)  # last: anything else in private chats
    return router
