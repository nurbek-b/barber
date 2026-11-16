"""Notifications created by a request are sent before its response, not on the next tick."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_now
from app.core.config import Settings
from app.main import create_app
from app.models import (
    Barber,
    BarberSchedule,
    BarberService,
    Branch,
    SalonSettings,
    Service,
    TelegramOutbox,
)
from app.models.enums import AdminRole, OutboxStatus
from app.worker.outbox import SendError
from tests.conftest import AdminFactory, login_as

TZ = ZoneInfo("Asia/Bishkek")
MONDAY = date(2026, 12, 7)


class FakeSender:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[int, str]] = []
        self.fail = fail

    async def send(self, chat_id: int, text: str, buttons: Any = None) -> None:
        if self.fail:
            raise SendError("telegram is down")
        self.sent.append((chat_id, text))


async def _world(session: AsyncSession, branch: Branch) -> tuple[Barber, Service]:
    salon = (await session.execute(select(SalonSettings))).scalar_one()
    salon.admin_chat_id = -100500
    service = Service(
        branch_id=branch.id, name_i18n={"ru": "Стрижка"}, duration_min=60, base_price=1
    )
    barber = Barber(branch_id=branch.id, name="Мастер")
    session.add_all([service, barber])
    await session.flush()
    session.add(BarberService(barber_id=barber.id, service_id=service.id))
    session.add_all(
        BarberSchedule(barber_id=barber.id, weekday=d, start_time=time(10), end_time=time(19))
        for d in range(7)
    )
    await session.commit()
    return barber, service


@pytest.fixture
async def http_with(
    settings: Settings,
) -> AsyncIterator[Any]:
    apps: list[tuple[FastAPI, httpx.AsyncClient]] = []

    async def factory(sender: FakeSender) -> httpx.AsyncClient:
        app = create_app(
            settings, redis=FakeAsyncRedis(decode_responses=True), outbox_sender=sender
        )
        app.dependency_overrides[get_now] = lambda: datetime.combine(
            MONDAY, time(8), tzinfo=TZ
        ).astimezone(UTC)
        await app.router.lifespan_context(app).__aenter__()
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://testserver"
        )
        apps.append((app, client))
        return client

    yield factory
    for _, client in apps:
        await client.aclose()


async def _create(http: httpx.AsyncClient, barber: Barber, service: Service, hour: int) -> None:
    response = await http.post(
        "/api/v1/admin/bookings",
        json={
            "client": {"name": "Звонок", "phone": f"+99670000{hour:04d}"},
            "barber_id": str(barber.id),
            "service_ids": [str(service.id)],
            "start_at": datetime.combine(MONDAY, time(hour), tzinfo=TZ).isoformat(),
        },
    )
    assert response.status_code == 201, response.text


async def test_sent_before_the_response(
    http_with: Any, session: AsyncSession, branch: Branch, make_admin: AdminFactory
) -> None:
    barber, service = await _world(session, branch)
    sender = FakeSender()
    http = await http_with(sender)
    await login_as(http, await make_admin(AdminRole.OWNER))
    await _create(http, barber, service, 12)

    assert [chat for chat, _ in sender.sent] == [-100500]
    row = (await session.execute(select(TelegramOutbox))).scalar_one()
    assert row.status is OutboxStatus.SENT


async def test_failure_leaves_it_to_the_worker(
    http_with: Any, session: AsyncSession, branch: Branch, make_admin: AdminFactory
) -> None:
    barber, service = await _world(session, branch)
    http = await http_with(FakeSender(fail=True))
    await login_as(http, await make_admin(AdminRole.OWNER))
    await _create(http, barber, service, 13)  # the request itself still succeeds

    row = (await session.execute(select(TelegramOutbox))).scalar_one()
    assert row.status is OutboxStatus.FAILED  # retried by the worker with backoff
    assert row.attempts == 1
