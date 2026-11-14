"""Test infrastructure.

Requires PostgreSQL (btree_gist). The schema is created by running the real Alembic
migrations, so migrations are tested on every run. Redis is replaced with fakeredis.

    TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/barber_test pytest
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic.config import Config
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from app.cli import create_admin, init_salon
from app.core.config import Environment, Settings
from app.core.security.initdata import build_init_data
from app.core.security.tokens import CSRF_COOKIE, CSRF_HEADER
from app.main import create_app
from app.models import AdminUser, Barber, Branch
from app.models.enums import AdminRole

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://localhost:7432/barber_test"
)
BOT_TOKEN = "123456:TEST-bot-token"
PASSWORD = "correct-horse-battery"


@pytest.fixture(scope="session")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    return Settings(
        env=Environment.TEST,
        database_url=TEST_DATABASE_URL,
        bot_token=BOT_TOKEN,
        jwt_secret="test-jwt-secret-" + "x" * 32,
        webhook_secret="test-webhook-secret",
        cookie_secure=True,
        log_json=False,
        log_level="WARNING",
        media_dir=str(tmp_path_factory.mktemp("media")),
    )


def _migrate(url: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    # env.py calls asyncio.run(); run it in a thread that has no running loop.
    await asyncio.to_thread(_migrate, settings.database_url)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
async def table_names(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename <> 'alembic_version'"
            )
        )
        return [row[0] for row in result]


@pytest.fixture(autouse=True)
async def _clean_db(engine: AsyncEngine, table_names: list[str]) -> AsyncIterator[None]:
    yield
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(table_names)} RESTART IDENTITY CASCADE"))


@pytest.fixture
def maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def session(maker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with maker() as session:
        yield session


@pytest.fixture
async def redis() -> AsyncIterator[FakeAsyncRedis]:
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.flushall()
    await client.aclose()


@pytest.fixture
async def app(settings: Settings, redis: FakeAsyncRedis) -> AsyncIterator[FastAPI]:
    application = create_app(settings, redis=redis)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    # https: so that Secure cookies are sent back by httpx.
    transport = httpx.ASGITransport(app=app, client=("10.0.0.1", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as http:
        yield http


@pytest.fixture
async def branch(session: AsyncSession) -> Branch:
    return await init_salon(session, "Test Barbershop")


# ---------------- admin helpers ----------------

AdminFactory = Callable[..., Awaitable[AdminUser]]


@pytest.fixture
def make_admin(session: AsyncSession, branch: Branch) -> AdminFactory:
    async def factory(
        role: AdminRole = AdminRole.OWNER,
        login: str | None = None,
        barber_id: uuid.UUID | None = None,
    ) -> AdminUser:
        admin = await create_admin(
            session, login or f"{role.value}-{uuid.uuid4().hex[:6]}", PASSWORD, role, "Test"
        )
        if barber_id is not None:
            admin.barber_id = barber_id
            await session.commit()
        return admin

    return factory


async def login_as(http: httpx.AsyncClient, admin: AdminUser) -> httpx.AsyncClient:
    response = await http.post(
        "/api/v1/admin/auth/login", json={"login": admin.login, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    http.headers[CSRF_HEADER] = http.cookies[CSRF_COOKIE]
    return http


@pytest.fixture
async def owner_client(client: httpx.AsyncClient, make_admin: AdminFactory) -> httpx.AsyncClient:
    return await login_as(client, await make_admin(AdminRole.OWNER))


@pytest.fixture
async def make_barber(session: AsyncSession, branch: Branch) -> Callable[..., Awaitable[Barber]]:
    async def factory(name: str = "Азамат", **kwargs: Any) -> Barber:
        barber = Barber(branch_id=branch.id, name=name, **kwargs)
        session.add(barber)
        await session.commit()
        return barber

    return factory


# ---------------- mini app helpers ----------------


def tma_header(
    telegram_id: int = 1001,
    *,
    first_name: str = "Бек",
    language_code: str = "ru",
    start_param: str | None = None,
    auth_date: int | None = None,
    bot_token: str = BOT_TOKEN,
) -> dict[str, str]:
    fields = {
        "user": json.dumps(
            {
                "id": telegram_id,
                "first_name": first_name,
                "username": f"user{telegram_id}",
                "language_code": language_code,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AAH-test",
    }
    if start_param:
        fields["start_param"] = start_param
    return {"Authorization": f"tma {build_init_data(fields, bot_token)}"}
