"""Telegram message templates (HTML parse mode).

Defaults live here; the salon can override any key/language in
`salon_settings.notification_templates = {"<key>": {"ru": "...", "ky": "...", "en": "..."}}`.
Placeholders use str.format syntax; values are HTML-escaped before substitution.
"""

from __future__ import annotations

import html
from collections.abc import Mapping
from typing import Any

FALLBACK_LANGUAGE = "ru"

DEFAULTS: dict[str, dict[str, str]] = {
    "booking_created_client": {
        "ru": "✅ <b>Вы записаны</b>\n{when}\nМастер: {barber}\nУслуги: {services}\n"
        "Сумма: {total_due}{bonus_line_ru}\n\n{salon}",
        "ky": "✅ <b>Сиз жазылдыңыз</b>\n{when}\nУстат: {barber}\nКызматтар: {services}\n"
        "Сумма: {total_due}{bonus_line_ky}\n\n{salon}",
        "en": "✅ <b>You're booked</b>\n{when}\nBarber: {barber}\nServices: {services}\n"
        "Total: {total_due}{bonus_line_en}\n\n{salon}",
    },
    "booking_created_admin": {
        "ru": "🆕 <b>Новая запись</b>\n{when}\nКлиент: {client} {phone}\nМастер: {barber}\n"
        "Услуги: {services}\nСумма: {subtotal}, бонусами: {bonus_spent}, к оплате: {total_due}"
        "\nИсточник: {source}",
        "ky": "🆕 <b>Жаңы жазылуу</b>\n{when}\nКардар: {client} {phone}\nУстат: {barber}\n"
        "Кызматтар: {services}\nСумма: {subtotal}, бонус: {bonus_spent}, төлөөгө: {total_due}"
        "\nБулак: {source}",
        "en": "🆕 <b>New booking</b>\n{when}\nClient: {client} {phone}\nBarber: {barber}\n"
        "Services: {services}\nTotal: {subtotal}, bonuses: {bonus_spent}, due: {total_due}"
        "\nSource: {source}",
    },
    "booking_created_barber": {
        "ru": "🆕 Новая запись к вам: {when}\n{client}\n{services}",
        "ky": "🆕 Сизге жаңы жазылуу: {when}\n{client}\n{services}",
        "en": "🆕 New booking for you: {when}\n{client}\n{services}",
    },
    "booking_cancelled_client": {
        "ru": "❌ Запись на {when} отменена.",
        "ky": "❌ {when} жазылуу жокко чыгарылды.",
        "en": "❌ Your booking for {when} was cancelled.",
    },
    "booking_cancelled_admin": {
        "ru": "❌ <b>Отмена</b> ({cancelled_by})\n{when}\nКлиент: {client} {phone}\n"
        "Мастер: {barber}\nУслуги: {services}\nСумма: {total_due}\nПричина: {reason}",
        "ky": "❌ <b>Жокко чыгаруу</b> ({cancelled_by})\n{when}\nКардар: {client} {phone}\n"
        "Устат: {barber}\nКызматтар: {services}\nСумма: {total_due}\nСебеби: {reason}",
        "en": "❌ <b>Cancelled</b> ({cancelled_by})\n{when}\nClient: {client} {phone}\n"
        "Barber: {barber}\nServices: {services}\nTotal: {total_due}\nReason: {reason}",
    },
    "booking_cancelled_barber": {
        "ru": "❌ Отменена запись {when}: {client}",
        "ky": "❌ {when} жазылуу жокко чыгарылды: {client}",
        "en": "❌ Booking {when} cancelled: {client}",
    },
    "booking_rescheduled_client": {
        "ru": "🔁 Запись перенесена: {old_when} → <b>{when}</b>\nМастер: {barber}",
        "ky": "🔁 Жазылуу которулду: {old_when} → <b>{when}</b>\nУстат: {barber}",
        "en": "🔁 Booking moved: {old_when} → <b>{when}</b>\nBarber: {barber}",
    },
    "booking_rescheduled_admin": {
        "ru": "🔁 <b>Перенос</b>\n{old_when} → {when}\nКлиент: {client} {phone}\n"
        "Мастер: {barber}\nУслуги: {services}\nСумма: {total_due}",
        "ky": "🔁 <b>Которуу</b>\n{old_when} → {when}\nКардар: {client} {phone}\n"
        "Устат: {barber}\nКызматтар: {services}\nСумма: {total_due}",
        "en": "🔁 <b>Rescheduled</b>\n{old_when} → {when}\nClient: {client} {phone}\n"
        "Barber: {barber}\nServices: {services}\nTotal: {total_due}",
    },
    "booking_rescheduled_barber": {
        "ru": "🔁 Перенос: {old_when} → {when}, {client}",
        "ky": "🔁 Которуу: {old_when} → {when}, {client}",
        "en": "🔁 Moved: {old_when} → {when}, {client}",
    },
    "bonus_earned_client": {
        "ru": "🎁 Начислено <b>{amount}</b> бонусов за визит.\nБаланс: {balance}",
        "ky": "🎁 Визит үчүн <b>{amount}</b> бонус берилди.\nБаланс: {balance}",
        "en": "🎁 <b>{amount}</b> bonuses for your visit.\nBalance: {balance}",
    },
    "bonus_credited_client": {
        "ru": "🎁 {reason}: +<b>{amount}</b> бонусов.\nБаланс: {balance}",
        "ky": "🎁 {reason}: +<b>{amount}</b> бонус.\nБаланс: {balance}",
        "en": "🎁 {reason}: +<b>{amount}</b> bonuses.\nBalance: {balance}",
    },
    "bonus_expiring_client": {
        "ru": "⏳ {amount} бонусов сгорят {date}. Успейте записаться!",
        "ky": "⏳ {amount} бонус {date} күйүп кетет. Жазылып калыңыз!",
        "en": "⏳ {amount} bonuses expire on {date}. Book a visit to use them!",
    },
    "rate_visit_client": {
        "ru": "Как вам визит к мастеру {barber}? Оцените, пожалуйста 🙏",
        "ky": "{barber} устатка болгон визит кандай болду? Баалап коюңузчу 🙏",
        "en": "How was your visit to {barber}? Please rate it 🙏",
    },
    "revisit_client": {
        "ru": (
            "Здравствуйте, {name}! С последнего визита к мастеру {barber} прошло {days} дн. ✂️\n"
            "Записаться снова — пара нажатий."
        ),
        "ky": (
            "Саламатсызбы, {name}! {barber} устатка акыркы келгениңизден бери {days} күн өттү. ✂️\n"
            "Кайра жазылуу — бир нече басуу."
        ),
        "en": (
            "Hi {name}! It's been {days} days since your visit to {barber}. ✂️\n"
            "Booking again takes a couple of taps."
        ),
    },
    "reminder_client": {
        "ru": "⏰ Напоминаем: {when}\nМастер: {barber}\nУслуги: {services}\n\n{salon}",
        "ky": "⏰ Эскертүү: {when}\nУстат: {barber}\nКызматтар: {services}\n\n{salon}",
        "en": "⏰ Reminder: {when}\nBarber: {barber}\nServices: {services}\n\n{salon}",
    },
}


class _SafeDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""


def _bonus_lines(values: Mapping[str, Any]) -> dict[str, str]:
    spent = values.get("bonus_spent_raw", 0)
    if not spent:
        return {"bonus_line_ru": "", "bonus_line_ky": "", "bonus_line_en": ""}
    amount = html.escape(str(values.get("bonus_spent", "")))
    return {
        "bonus_line_ru": f" (бонусами {amount})",
        "bonus_line_ky": f" (бонус менен {amount})",
        "bonus_line_en": f" ({amount} in bonuses)",
    }


def render(
    key: str,
    language: str,
    values: Mapping[str, Any],
    overrides: Mapping[str, Any] | None = None,
) -> str:
    """Pick override → default for the language → default for ru; then fill placeholders."""
    candidates: list[str | None] = []
    override = (overrides or {}).get(key)
    if isinstance(override, Mapping):
        candidates += [override.get(language), override.get(FALLBACK_LANGUAGE)]
    default = DEFAULTS.get(key, {})
    candidates += [default.get(language), default.get(FALLBACK_LANGUAGE)]
    template = next((item for item in candidates if isinstance(item, str) and item), None)
    if template is None:
        raise KeyError(f"unknown template {key!r}")
    escaped = _SafeDict(
        {name: html.escape(str(value)) for name, value in values.items() if value is not None}
    )
    escaped.update(_bonus_lines(values))
    try:
        return template.format_map(escaped)
    except (ValueError, IndexError):
        # A broken salon override must never block notifications.
        fallback = default.get(language) or default[FALLBACK_LANGUAGE]
        return fallback.format_map(escaped)


CURRENCY_LABEL = {"KGS": "сом", "KZT": "₸", "RUB": "₽", "UZS": "сум"}


def format_money(amount: int, currency: str) -> str:
    """1234500 tyiyn → '12 345 сом'; kopecks shown only when non-zero."""
    sign = "-" if amount < 0 else ""
    major, minor = divmod(abs(amount), 100)
    body = f"{major:,}".replace(",", " ")
    if minor:
        body += f",{minor:02d}"
    return f"{sign}{body} {CURRENCY_LABEL.get(currency, currency)}"
