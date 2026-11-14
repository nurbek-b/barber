"""One-off bot configuration through the Bot API (run on deploy or after changing URLs)."""

from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot
from aiogram.types import BotCommand, MenuButtonDefault, MenuButtonWebApp, WebAppInfo

from app.bot.main import ALLOWED_UPDATES, WEBHOOK_PATH
from app.bot.texts import COMMANDS, t
from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class SetupReport:
    webhook_url: str
    menu_button: str
    commands: dict[str, int]


async def configure_bot(bot: Bot, settings: Settings, public_url: str) -> SetupReport:
    """public_url: https origin that Telegram can reach (domain, ngrok or cloudflared)."""
    if not public_url.startswith("https://"):
        raise ValueError("Telegram requires an https:// webhook URL")
    secret = settings.webhook_secret.get_secret_value()
    if not secret:
        raise ValueError("WEBHOOK_SECRET is not configured")
    webhook_url = public_url.rstrip("/") + WEBHOOK_PATH
    await bot.set_webhook(
        url=webhook_url,
        secret_token=secret,
        allowed_updates=ALLOWED_UPDATES,
        drop_pending_updates=True,
    )
    commands: dict[str, int] = {}
    for lang, items in COMMANDS.items():
        await bot.set_my_commands(
            [BotCommand(command=name, description=desc) for name, desc in items],
            language_code=None if lang == "ru" else lang,
        )
        commands[lang] = len(items)

    if settings.miniapp_url:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text=t("menu_button", "ru"), web_app=WebAppInfo(url=settings.miniapp_url)
            )
        )
        menu = settings.miniapp_url
    else:
        await bot.set_chat_menu_button(menu_button=MenuButtonDefault())
        menu = "default (MINIAPP_URL is empty)"
    return SetupReport(webhook_url=webhook_url, menu_button=menu, commands=commands)
