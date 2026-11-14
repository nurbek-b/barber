from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_now
from app.models import Barber, BarberService, Booking, Branch, Client, Service
from app.models.enums import AdminRole, BookingStatus
from tests.conftest import AdminFactory, login_as, tma_header

TZ = ZoneInfo("Asia/Bishkek")
MONDAY = date(2026, 12, 7)
TUESDAY = MONDAY + timedelta(days=1)
ADMIN = "/api/v1/admin"
MINI = "/api/v1/miniapp"


def local(day: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=TZ).astimezone(UTC)


def hhmm(values: list[dict[str, Any]]) -> list[str]:
    return [
        datetime.fromisoformat(item["start_at"]).astimezone(TZ).strftime("%H:%M") for item in values
    ]


@pytest.fixture
def clock(app: FastAPI) -> Iterator[list[datetime]]:
    """Mutable 'now': tests set clock[0]. Default — Monday 08:00 in Bishkek."""
    current = [local(MONDAY, 8)]
    app.dependency_overrides[get_now] = lambda: current[0]
    yield current
    app.dependency_overrides.pop(get_now, None)


class World:
    def __init__(self, branch: Branch) -> None:
        self.branch = branch
        self.haircut = Service(
            branch_id=branch.id, name_i18n={"ru": "Стрижка"}, duration_min=60, base_price=80_000
        )
        self.beard = Service(
            branch_id=branch.id, name_i18n={"ru": "Борода"}, duration_min=30, base_price=50_000
        )
        self.first = Barber(branch_id=branch.id, name="Первый", sort_order=1)
        self.second = Barber(branch_id=branch.id, name="Второй", sort_order=2)
        self.client = Client(branch_id=branch.id, name="Клиент", referral_code="worldcli")


@pytest.fixture
async def world(session: AsyncSession, branch: Branch) -> World:
    w = World(branch)
    session.add_all([w.haircut, w.beard, w.first, w.second, w.client])
    await session.flush()
    session.add_all(
        [
            BarberService(barber_id=w.first.id, service_id=w.haircut.id),
            BarberService(barber_id=w.first.id, service_id=w.beard.id),
            # second barber is slower at haircuts
            BarberService(barber_id=w.second.id, service_id=w.haircut.id, duration_min=90),
        ]
    )
    await session.commit()
    return w


async def put_week(
    http: httpx.AsyncClient, barber: Barber, start: str = "10:00", end: str = "19:00"
) -> httpx.Response:
    return await http.put(
        f"{ADMIN}/barbers/{barber.id}/schedule",
        json={
            "intervals": [
                {"weekday": weekday, "start_time": start, "end_time": end} for weekday in range(7)
            ]
        },
    )


async def add_booking(
    session: AsyncSession, world: World, barber: Barber, start: datetime, minutes: int
) -> Booking:
    booking = Booking(
        branch_id=world.branch.id,
        client_id=world.client.id,
        barber_id=barber.id,
        status=BookingStatus.CONFIRMED,
        start_at=start,
        end_at=start + timedelta(minutes=minutes),
        blocked_until=start + timedelta(minutes=minutes),
        subtotal=80_000,
        bonus_spent=0,
        total_due=80_000,
    )
    session.add(booking)
    await session.commit()
    return booking


# ---------------------------------------------------------------------------
# weekly template
# ---------------------------------------------------------------------------


async def test_weekly_schedule_roundtrip(owner_client: httpx.AsyncClient, world: World) -> None:
    response = await owner_client.put(
        f"{ADMIN}/barbers/{world.first.id}/schedule",
        json={
            "intervals": [
                {"weekday": 1, "start_time": "15:00", "end_time": "19:00"},
                {"weekday": 1, "start_time": "10:00", "end_time": "14:00"},
                {"weekday": 5, "start_time": "20:00", "end_time": "02:00"},
            ]
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["conflicting_bookings"] == []
    got = [(i["weekday"], i["start_time"], i["end_time"]) for i in body["intervals"]]
    assert got == [
        (1, "10:00:00", "14:00:00"),
        (1, "15:00:00", "19:00:00"),
        (5, "20:00:00", "02:00:00"),
    ]
    fetched = await owner_client.get(f"{ADMIN}/barbers/{world.first.id}/schedule")
    assert fetched.json()["intervals"] == body["intervals"]


@pytest.mark.parametrize(
    "intervals",
    [
        [
            {"weekday": 0, "start_time": "10:00", "end_time": "14:00"},
            {"weekday": 0, "start_time": "13:00", "end_time": "19:00"},
        ],
        [
            {"weekday": 0, "start_time": "20:00", "end_time": "03:00"},
            {"weekday": 1, "start_time": "02:00", "end_time": "10:00"},
        ],
    ],
)
async def test_weekly_overlap_rejected(
    owner_client: httpx.AsyncClient, world: World, intervals: list[dict[str, Any]]
) -> None:
    response = await owner_client.put(
        f"{ADMIN}/barbers/{world.first.id}/schedule", json={"intervals": intervals}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "schedule_overlap"


@pytest.mark.parametrize(
    "interval",
    [
        {"weekday": 7, "start_time": "10:00", "end_time": "19:00"},
        {"weekday": 0, "start_time": "10:00", "end_time": "10:00"},
        {"weekday": 0, "start_time": "10:00:30", "end_time": "19:00"},
    ],
)
async def test_weekly_validation(
    owner_client: httpx.AsyncClient, world: World, interval: dict[str, Any]
) -> None:
    response = await owner_client.put(
        f"{ADMIN}/barbers/{world.first.id}/schedule", json={"intervals": [interval]}
    )
    assert response.status_code == 422


async def test_schedule_change_reports_conflicting_bookings(
    owner_client: httpx.AsyncClient, world: World, session: AsyncSession, clock: list[datetime]
) -> None:
    await put_week(owner_client, world.first)
    booking = await add_booking(session, world, world.first, local(TUESDAY, 17), 60)

    response = await put_week(owner_client, world.first, "10:00", "16:00")
    conflicts = response.json()["conflicting_bookings"]
    assert [item["id"] for item in conflicts] == [str(booking.id)]


# ---------------------------------------------------------------------------
# exceptions
# ---------------------------------------------------------------------------


async def test_exception_crud(
    owner_client: httpx.AsyncClient, world: World, session: AsyncSession, clock: list[datetime]
) -> None:
    await put_week(owner_client, world.first)
    booking = await add_booking(session, world, world.first, local(TUESDAY, 12), 60)
    url = f"{ADMIN}/barbers/{world.first.id}/exceptions"

    created = await owner_client.post(
        url, json={"date_from": str(TUESDAY), "date_to": str(TUESDAY), "kind": "day_off"}
    )
    assert created.status_code == 201, created.text
    exc_id = created.json()["exception"]["id"]
    assert [b["id"] for b in created.json()["conflicting_bookings"]] == [str(booking.id)]

    overlap = await owner_client.post(
        url,
        json={
            "date_from": str(MONDAY),
            "date_to": str(TUESDAY + timedelta(days=3)),
            "kind": "vacation",
        },
    )
    assert overlap.status_code == 409
    assert overlap.json()["error"]["code"] == "exception_overlap"

    updated = await owner_client.put(
        f"{url}/{exc_id}",
        json={
            "date_from": str(TUESDAY),
            "date_to": str(TUESDAY),
            "kind": "custom_hours",
            "intervals": [{"start": "11:00", "end": "15:00"}],
            "note": "короткий день",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["exception"]["intervals"] == [{"start": "11:00:00", "end": "15:00:00"}]
    assert updated.json()["conflicting_bookings"] == []

    listed = await owner_client.get(
        url, params={"date_from": str(MONDAY), "date_to": str(MONDAY + timedelta(days=7))}
    )
    assert [item["id"] for item in listed.json()] == [exc_id]

    assert (await owner_client.delete(f"{url}/{exc_id}")).status_code == 204
    assert (await owner_client.delete(f"{url}/{exc_id}")).status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"date_from": "2026-12-08", "date_to": "2026-12-08", "kind": "custom_hours"},
        {
            "date_from": "2026-12-08",
            "date_to": "2026-12-08",
            "kind": "day_off",
            "intervals": [{"start": "10:00", "end": "12:00"}],
        },
        {"date_from": "2026-12-09", "date_to": "2026-12-08", "kind": "day_off"},
        {"date_from": "2026-01-01", "date_to": "2027-06-01", "kind": "vacation"},
        {
            "date_from": "2026-12-08",
            "date_to": "2026-12-08",
            "kind": "custom_hours",
            "intervals": [{"start": "10:00", "end": "13:00"}, {"start": "12:00", "end": "15:00"}],
        },
    ],
)
async def test_exception_validation(
    owner_client: httpx.AsyncClient, world: World, payload: dict[str, Any]
) -> None:
    response = await owner_client.post(f"{ADMIN}/barbers/{world.first.id}/exceptions", json=payload)
    assert response.status_code == 422


async def test_barber_role_reads_own_schedule_only(
    client: httpx.AsyncClient, world: World, make_admin: AdminFactory
) -> None:
    await login_as(client, await make_admin(AdminRole.BARBER, barber_id=world.first.id))
    assert (await client.get(f"{ADMIN}/barbers/{world.first.id}/schedule")).status_code == 200
    assert (await client.get(f"{ADMIN}/barbers/{world.second.id}/schedule")).status_code == 403
    assert (await put_week(client, world.first)).status_code == 403


# ---------------------------------------------------------------------------
# availability
# ---------------------------------------------------------------------------


async def test_slots_for_barber(
    owner_client: httpx.AsyncClient,
    client: httpx.AsyncClient,
    world: World,
    session: AsyncSession,
    clock: list[datetime],
) -> None:
    await put_week(owner_client, world.first)
    await add_booking(session, world, world.first, local(MONDAY, 12), 60)

    response = await client.get(
        f"{MINI}/availability/slots",
        headers=tma_header(),
        params={
            "date": str(MONDAY),
            "barber_id": str(world.first.id),
            "service_ids": [str(world.haircut.id), str(world.beard.id)],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["timezone"] == "Asia/Bishkek"
    assert body["durations"] == {str(world.first.id): 90}
    times = hhmm(body["slots"])
    assert times[0] == "10:00"
    assert "10:30" in times  # 10:30 + 90 = 12:00
    assert "10:45" not in times
    assert "12:30" not in times
    assert times[times.index("10:30") + 1] == "13:00"
    assert times[-1] == "17:30"
    assert all(slot["barber_ids"] == [str(world.first.id)] for slot in body["slots"])


async def test_slots_any_barber_union(
    owner_client: httpx.AsyncClient, client: httpx.AsyncClient, world: World, clock: list[datetime]
) -> None:
    await put_week(owner_client, world.first, "10:00", "12:00")
    await put_week(owner_client, world.second, "11:00", "13:00")
    response = await client.get(
        f"{MINI}/availability/slots",
        headers=tma_header(),
        params={"date": str(MONDAY), "service_ids": [str(world.haircut.id)]},
    )
    body = response.json()
    assert body["durations"] == {str(world.first.id): 60, str(world.second.id): 90}
    by_time = {
        datetime.fromisoformat(s["start_at"]).astimezone(TZ).strftime("%H:%M"): s["barber_ids"]
        for s in body["slots"]
    }
    first, second = str(world.first.id), str(world.second.id)
    assert by_time["10:00"] == [first]
    assert by_time["11:00"] == [first, second]
    assert by_time["11:30"] == [second]
    assert "11:45" not in by_time


async def test_any_barber_requires_all_services(
    owner_client: httpx.AsyncClient, client: httpx.AsyncClient, world: World, clock: list[datetime]
) -> None:
    await put_week(owner_client, world.first)
    await put_week(owner_client, world.second)
    response = await client.get(
        f"{MINI}/availability/slots",
        headers=tma_header(),
        params={"date": str(MONDAY), "service_ids": [str(world.haircut.id), str(world.beard.id)]},
    )
    assert list(response.json()["durations"]) == [str(world.first.id)]

    not_offered = await client.get(
        f"{MINI}/availability/slots",
        headers=tma_header(),
        params={
            "date": str(MONDAY),
            "barber_id": str(world.second.id),
            "service_ids": [str(world.beard.id)],
        },
    )
    assert not_offered.status_code == 422
    assert not_offered.json()["error"]["code"] == "services_not_offered"


async def test_lead_time_and_past(
    owner_client: httpx.AsyncClient, client: httpx.AsyncClient, world: World, clock: list[datetime]
) -> None:
    await put_week(owner_client, world.first)
    clock[0] = local(MONDAY, 12, 7)  # lead time 60 min by default
    params = {"barber_id": str(world.first.id), "service_ids": [str(world.beard.id)]}
    today = await client.get(
        f"{MINI}/availability/slots", headers=tma_header(), params={**params, "date": str(MONDAY)}
    )
    assert hhmm(today.json()["slots"])[0] == "13:15"

    past = await client.get(
        f"{MINI}/availability/slots",
        headers=tma_header(),
        params={**params, "date": str(MONDAY - timedelta(days=1))},
    )
    assert past.json()["slots"] == []


async def test_days_calendar_and_horizon(
    owner_client: httpx.AsyncClient, client: httpx.AsyncClient, world: World, clock: list[datetime]
) -> None:
    await put_week(owner_client, world.first)
    await owner_client.post(
        f"{ADMIN}/barbers/{world.first.id}/exceptions",
        json={"date_from": str(TUESDAY), "date_to": str(TUESDAY), "kind": "day_off"},
    )
    response = await client.get(
        f"{MINI}/availability/days",
        headers=tma_header(),
        params={"barber_id": str(world.first.id), "service_ids": [str(world.haircut.id)]},
    )
    days = {item["date"]: item["slots_count"] for item in response.json()["days"]}
    assert days[str(MONDAY)] == 33
    assert days[str(TUESDAY)] == 0
    assert len(days) == 31  # today + max_days_ahead (30)
    assert str(MONDAY + timedelta(days=31)) not in days


async def test_admin_view_ignores_lead_time_and_online_flag(
    owner_client: httpx.AsyncClient,
    client: httpx.AsyncClient,
    world: World,
    session: AsyncSession,
    clock: list[datetime],
) -> None:
    await put_week(owner_client, world.first)
    world.first.is_bookable_online = False
    await session.commit()
    clock[0] = local(MONDAY, 9, 50)
    params = {
        "date": str(MONDAY),
        "barber_id": str(world.first.id),
        "service_ids": [str(world.beard.id)],
    }

    hidden = await client.get(f"{MINI}/availability/slots", headers=tma_header(), params=params)
    assert hidden.status_code == 404

    staff = await owner_client.get(f"{ADMIN}/availability/slots", params=params)
    assert staff.status_code == 200
    assert hhmm(staff.json()["slots"])[0] == "10:00"


async def test_cache_is_invalidated_by_schedule_changes(
    owner_client: httpx.AsyncClient,
    client: httpx.AsyncClient,
    world: World,
    redis: FakeAsyncRedis,
    clock: list[datetime],
) -> None:
    await put_week(owner_client, world.first)
    params = {
        "date": str(TUESDAY),
        "barber_id": str(world.first.id),
        "service_ids": [str(world.haircut.id)],
    }
    first = await client.get(f"{MINI}/availability/slots", headers=tma_header(), params=params)
    assert len(first.json()["slots"]) == 33
    assert await redis.keys("slots:*:2026-12-08:*")

    await owner_client.post(
        f"{ADMIN}/barbers/{world.first.id}/exceptions",
        json={"date_from": str(TUESDAY), "date_to": str(TUESDAY), "kind": "day_off"},
    )
    second = await client.get(f"{MINI}/availability/slots", headers=tma_header(), params=params)
    assert second.json()["slots"] == []


async def test_works_when_redis_is_down(
    owner_client: httpx.AsyncClient,
    client: httpx.AsyncClient,
    world: World,
    redis: FakeAsyncRedis,
    clock: list[datetime],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await put_week(owner_client, world.first)

    calls: list[str] = []

    def broken(name: str) -> Any:
        def fail(*args: Any, **kwargs: Any) -> Any:
            calls.append(name)
            raise RedisConnectionError("redis is down")

        return fail

    monkeypatch.setattr(redis, "mget", broken("mget"))
    monkeypatch.setattr(redis, "pipeline", broken("pipeline"))
    response = await client.get(
        f"{MINI}/availability/slots",
        headers=tma_header(),
        params={"date": str(MONDAY), "service_ids": [str(world.haircut.id)]},
    )
    # initData auth doesn't touch Redis; slots are computed without the cache
    assert response.status_code == 200
    assert len(response.json()["slots"]) == 33
    assert "mget" in calls, "the cache must have been tried"


@contextmanager
def count_queries(app: FastAPI) -> Iterator[list[str]]:
    statements: list[str] = []

    def listener(*args: Any) -> None:
        statements.append(str(args[2]))

    sync_engine = app.state.engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", listener)
    try:
        yield statements
    finally:
        event.remove(sync_engine, "before_cursor_execute", listener)


async def test_query_count_does_not_grow_with_barbers(
    app: FastAPI,
    owner_client: httpx.AsyncClient,
    client: httpx.AsyncClient,
    world: World,
    session: AsyncSession,
    redis: FakeAsyncRedis,
    clock: list[datetime],
) -> None:
    headers = tma_header()
    await client.get(f"{MINI}/me", headers=headers)  # register the client beforehand
    params = {"service_ids": [str(world.haircut.id)]}

    async def measure() -> int:
        await redis.flushall()
        with count_queries(app) as statements:
            response = await client.get(f"{MINI}/availability/days", headers=headers, params=params)
        assert response.status_code == 200
        return len(statements)

    await put_week(owner_client, world.first)
    few = await measure()

    for index in range(8):
        barber = Barber(branch_id=world.branch.id, name=f"Мастер {index}")
        session.add(barber)
        await session.flush()
        session.add(BarberService(barber_id=barber.id, service_id=world.haircut.id))
        await session.commit()
        await put_week(owner_client, barber)
    many = await measure()
    assert many == few, f"{few} queries for 2 barbers vs {many} for 10"
