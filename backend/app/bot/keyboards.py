from __future__ import annotations

from typing import Any

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from app.bot.texts import t
from app.core.config import Settings

LANGUAGES = (("ru", "🇷🇺 Русский"), ("ky", "🇰🇬 Кыргызча"), ("en", "🇬🇧 English"))


def app_button(
    settings: Settings, lang: str, start_param: str | None = None
) -> InlineKeyboardButton:
    """WebApp button when the Mini App URL is configured, otherwise a t.me deep link."""
    if settings.miniapp_url:
        url = settings.miniapp_url
        if start_param:
            url += ("&" if "?" in url else "?") + f"startapp={start_param}"
        return InlineKeyboardButton(text=t("open_app", lang), web_app=WebAppInfo(url=url))
    link = f"https://t.me/{settings.bot_username}/{settings.miniapp_short_name}"
    if start_param:
        link += f"?startapp={start_param}"
    return InlineKeyboardButton(text=t("open_app", lang), url=link)


def open_app(settings: Settings, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[app_button(settings, lang)]])


def share_phone(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t("share_phone", lang), request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def languages() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=f"lang:{code}")]
            for code, label in LANGUAGES
        ]
    )


def from_payload(rows: list[list[dict[str, Any]]] | None) -> InlineKeyboardMarkup | None:
    """Outbox messages carry buttons as JSON: [[{"text", "callback_data"|"url"|"web_app"}]]."""
    if not rows:
        return None
    keyboard = []
    for row in rows:
        buttons = []
        for item in row:
            if "web_app" in item:
                buttons.append(
                    InlineKeyboardButton(text=item["text"], web_app=WebAppInfo(url=item["web_app"]))
                )
            elif "url" in item:
                buttons.append(InlineKeyboardButton(text=item["text"], url=item["url"]))
            else:
                buttons.append(
                    InlineKeyboardButton(text=item["text"], callback_data=item["callback_data"])
                )
        keyboard.append(buttons)
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
