"""WebSocket tests run Starlette's sync TestClient in a worker thread with its own event loop,
its own app instance and its own fakeredis — the same way a real process would."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from fakeredis import FakeAsyncRedis
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.deps import get_now
from app.core.config import Settings
from app.main import create_app
from app.models import Barber, BarberSchedule, BarberService, Branch, Service
from app.models.enums import AdminRole
from tests.conftest import PASSWORD, AdminFactory

TZ = ZoneInfo("Asia/Bishkek")
MONDAY = date(2026, 12, 7)
WS = "/api/v1/admin/ws"


def local(hh: int) -> datetime:
    return datetime.combine(MONDAY, time(hh), tzinfo=TZ).astimezone(UTC)


@pytest.fixture
async def setup(session: AsyncSession, branch: Branch) -> tuple[Barber, Barber, Service]:
    service = Service(
        branch_id=branch.id, name_i18n={"ru": "Стрижка"}, duration_min=60, base_price=80_000
    )
    mine = Barber(branch_id=branch.id, name="Мой")
    other = Barber(branch_id=branch.id, name="Чужой")
    session.add_all([service, mine, other])
    await session.flush()
    for barber in (mine, other):
        session.add(BarberService(barber_id=barber.id, service_id=service.id))
        session.add_all(
            BarberSchedule(barber_id=barber.id, weekday=d, start_time=time(10), end_time=time(19))
            for d in range(7)
        )
    await session.commit()
    return mine, other, service


def _client(settings: Settings) -> TestClient:
    # TestClient talks ws:// (not wss://): Secure cookies would not be sent over it.
    insecure = settings.model_copy(update={"cookie_secure": False})
    app = create_app(insecure, redis=FakeAsyncRedis(decode_responses=True))
    app.dependency_overrides[get_now] = lambda: local(8)
    return TestClient(app, base_url="https://testserver")


def _login(http: TestClient, login: str) -> None:
    response = http.post("/api/v1/admin/auth/login", json={"login": login, "password": PASSWORD})
    assert response.status_code == 200, response.text
    http.headers["X-CSRF-Token"] = http.cookies["csrf_token"]


async def test_events_are_pushed_and_filtered_for_barbers(
    settings: Settings,
    make_admin: AdminFactory,
    setup: tuple[Barber, Barber, Service],
) -> None:
    mine, other, service = setup
    owner = await make_admin(AdminRole.OWNER)
    barber_account = await make_admin(AdminRole.BARBER, barber_id=mine.id)

    def scenario() -> tuple[dict[str, object], list[dict[str, object]], dict[str, object]]:
        with _client(settings) as http:
            # one app instance (one Redis) — switch the session cookie between the two sockets
            _login(http, barber_account.login)
            barber_cookies = dict(http.cookies)
            http.cookies.clear()
            _login(http, owner.login)
            owner_cookies = dict(http.cookies)
            with http.websocket_connect(WS) as owner_ws:
                hello = owner_ws.receive_json()
                http.cookies.clear()
                http.cookies.update(barber_cookies)
                with http.websocket_connect(WS) as barber_ws:
                    barber_ws.receive_json()
                    http.cookies.clear()
                    http.cookies.update(owner_cookies)
                    for barber, hour in ((other, 12), (mine, 13)):
                        response = http.post(
                            "/api/v1/admin/bookings",
                            json={
                                "client": {"name": "Звонок", "phone": f"+99670000{hour:04d}"},
                                "barber_id": str(barber.id),
                                "service_ids": [str(service.id)],
                                "start_at": local(hour).isoformat(),
                            },
                        )
                        assert response.status_code == 201, response.text
                    owner_events = [owner_ws.receive_json(), owner_ws.receive_json()]
                    barber_event = barber_ws.receive_json()
                    owner_ws.send_text("ping")
                    assert owner_ws.receive_json() == {"type": "pong"}
                    return hello, owner_events, barber_event

    hello, owner_events, barber_event = await asyncio.to_thread(scenario)
    assert hello["type"] == "hello"
    assert [e["event"]["payload"]["barber_id"] for e in owner_events] == [  # type: ignore[index]
        str(other.id),
        str(mine.id),
    ]
    assert barber_event["type"] == "event"
    assert barber_event["event"]["payload"]["barber_id"] == str(mine.id)  # type: ignore[index]
    assert barber_event["event"]["type"] == "booking_created"  # type: ignore[index]


async def test_rejects_anonymous_and_foreign_origin(
    settings: Settings, make_admin: AdminFactory, branch: Branch
) -> None:
    owner = await make_admin(AdminRole.OWNER)

    def scenario() -> list[int]:
        codes = []
        with _client(settings) as http:
            for headers in ({}, {"origin": "https://evil.example"}):
                if headers:
                    _login(http, owner.login)
                with (
                    pytest.raises(WebSocketDisconnect) as exc_info,
                    http.websocket_connect(WS, headers=headers) as ws,
                ):
                    ws.receive_json()
                codes.append(exc_info.value.code)
        return codes

    assert await asyncio.to_thread(scenario) == [1008, 1008]
