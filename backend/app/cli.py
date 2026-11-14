"""Management commands.

barber init                         # default branch, salon & bonus settings, loyalty levels
barber create-admin --login owner --role owner   # asks for the password
barber export-openapi openapi.json  # schema for packages/api-client (no DB needed)
barber bot-setup --public-url https://example.com   # webhook, commands, menu button
barber bot-info                     # current webhook status
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import create_engine, create_sessionmaker
from app.core.security.passwords import hash_password
from app.models import AdminUser, BonusSettings, Branch, LoyaltyLevel, SalonSettings
from app.models.enums import AdminRole, LevelRule

DEFAULT_LEVELS = (
    # name, min_visits, min_spent (tyiyn), cashback_bp
    ({"ru": "Бронза", "ky": "Коло", "en": "Bronze"}, 0, 0, 300, "#cd7f32"),
    ({"ru": "Серебро", "ky": "Күмүш", "en": "Silver"}, 5, 1_000_000, 500, "#c0c0c0"),
    ({"ru": "Золото", "ky": "Алтын", "en": "Gold"}, 15, 3_000_000, 700, "#ffd700"),
)


async def init_salon(session: AsyncSession, name: str) -> Branch:
    branch = await session.scalar(select(Branch).where(Branch.is_default.is_(True)))
    if branch is None:
        branch = Branch(slug="main", name=name, is_default=True)
        session.add(branch)
        await session.flush()
        print(f"created branch {branch.id}")

    if await session.get(SalonSettings, branch.id) is None:
        session.add(
            SalonSettings(
                branch_id=branch.id,
                name=name,
                timezone="Asia/Bishkek",
                currency="KGS",
                default_language="ru",
            )
        )
        print("created salon settings")

    if await session.get(BonusSettings, branch.id) is None:
        session.add(BonusSettings(branch_id=branch.id, level_rule=LevelRule.ANY))
        print("created bonus settings")

    has_levels = await session.scalar(
        select(LoyaltyLevel.id).where(LoyaltyLevel.branch_id == branch.id).limit(1)
    )
    if has_levels is None:
        for order, (level_name, visits, spent, cashback, color) in enumerate(DEFAULT_LEVELS):
            session.add(
                LoyaltyLevel(
                    branch_id=branch.id,
                    name_i18n=level_name,
                    min_visits=visits,
                    min_spent=spent,
                    cashback_bp=cashback,
                    color=color,
                    sort_order=order,
                )
            )
        print("created loyalty levels")
    await session.commit()
    return branch


async def create_admin(
    session: AsyncSession, login: str, password: str, role: AdminRole, full_name: str
) -> AdminUser:
    login = login.strip().lower()
    if await session.scalar(select(AdminUser).where(AdminUser.login == login)):
        raise SystemExit(f"admin '{login}' already exists")
    admin = AdminUser(
        login=login, password_hash=hash_password(password), role=role, full_name=full_name
    )
    session.add(admin)
    await session.commit()
    return admin


async def _run_db(action: Callable[[AsyncSession], Awaitable[object]]) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    maker = create_sessionmaker(engine)
    try:
        async with maker() as session:
            await action(session)
    finally:
        await engine.dispose()


async def _bot_command(command: str, public_url: str | None) -> None:
    from app.bot.factory import create_bot
    from app.bot.setup import configure_bot

    settings = get_settings()
    bot = create_bot(settings)
    try:
        if command == "bot-setup" and public_url:
            report = await configure_bot(bot, settings, public_url)
            print(f"webhook: {report.webhook_url}")
            print(f"menu button: {report.menu_button}")
            print(f"commands: {report.commands}")
        info = await bot.get_webhook_info()
        print(
            f"url={info.url!r} pending={info.pending_update_count} "
            f"last_error={info.last_error_message!r}"
        )
    finally:
        await bot.session.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="barber")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create default branch and settings (idempotent)")
    init.add_argument("--name", default="Barbershop")

    admin = sub.add_parser("create-admin", help="create a staff account")
    admin.add_argument("--login", required=True)
    admin.add_argument("--role", choices=[role.value for role in AdminRole], default="owner")
    admin.add_argument("--full-name", default="")
    admin.add_argument("--password-stdin", action="store_true", help="read password from stdin")

    export = sub.add_parser("export-openapi", help="write OpenAPI schema to a file")
    export.add_argument("path", type=Path)

    bot_setup = sub.add_parser("bot-setup", help="register webhook, commands and menu button")
    bot_setup.add_argument("--public-url", required=True, help="https origin reachable by Telegram")
    sub.add_parser("bot-info", help="show webhook info")

    args = parser.parse_args(argv)

    if args.command == "init":
        asyncio.run(_run_db(lambda session: init_salon(session, args.name)))
    elif args.command == "create-admin":
        if args.password_stdin:
            password = sys.stdin.readline().rstrip("\n")
        else:
            password = getpass.getpass("Password: ")
            if password != getpass.getpass("Repeat: "):
                raise SystemExit("passwords do not match")
        if len(password) < 10:
            raise SystemExit("password must be at least 10 characters")
        asyncio.run(
            _run_db(
                lambda session: create_admin(
                    session, args.login, password, AdminRole(args.role), args.full_name
                )
            )
        )
        print(f"created {args.role} '{args.login}'")
    elif args.command in ("bot-setup", "bot-info"):
        asyncio.run(_bot_command(args.command, getattr(args, "public_url", None)))
    elif args.command == "export-openapi":
        from app.main import create_app

        schema = create_app().openapi()
        args.path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n")
        print(f"wrote {args.path}")


if __name__ == "__main__":
    main()
