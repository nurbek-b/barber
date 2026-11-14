from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_now
from app.models import (
    AuditLog,
    Barber,
    BarberSchedule,
    BarberService,
    Booking,
    Branch,
    Client,
    Service,
    TelegramOutbox,
)
from app.models.enums import AdminRole
from tests.conftest import AdminFactory, login_as

TZ = ZoneInfo("Asia/Bishkek")
MONDAY = date(2026, 12, 7)
ADMIN = "/api/v1/admin"


def local(day: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=TZ).astimezone(UTC)


@pytest.fixture
def clock(app: FastAPI) -> Iterator[list[datetime]]:
    current = [local(MONDAY, 8)]
    app.dependency_overrides[get_now] = lambda: current[0]
    yield current
    app.dependency_overrides.pop(get_now, None)


class World:
    haircut: Service
    beard: Service
    first: Barber
    second: Barber


@pytest.fixture
async def world(session: AsyncSession, branch: Branch) -> World:
    w = World()
    w.haircut = Service(
        branch_id=branch.id, name_i18n={"ru": "Стрижка"}, duration_min=60, base_price=80_000
    )
    w.beard = Service(
        branch_id=branch.id, name_i18n={"ru": "Борода"}, duration_min=30, base_price=50_000
    )
    w.first = Barber(branch_id=branch.id, name="Первый", sort_order=1)
    w.second = Barber(branch_id=branch.id, name="Второй", sort_order=2, is_bookable_online=False)
    session.add_all([w.haircut, w.beard, w.first, w.second])
    await session.flush()
    for barber in (w.first, w.second):
        session.add_all(
            [
                BarberService(barber_id=barber.id, service_id=w.haircut.id),
                BarberService(barber_id=barber.id, service_id=w.beard.id),
            ]
        )
        for weekday in range(7):
            session.add(
                BarberSchedule(
                    barber_id=barber.id, weekday=weekday, start_time=time(10), end_time=time(19)
                )
            )
    await session.commit()
    return w


def payload(world: World, start: datetime, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "client": {"name": "Звонок", "phone": "+996 700 111 222"},
        "barber_id": str(world.first.id),
        "service_ids": [str(world.haircut.id)],
        "start_at": start.isoformat(),
    }
    body.update(extra)
    return body


async def create(
    http: httpx.AsyncClient, world: World, start: datetime, **extra: Any
) -> dict[str, Any]:
    response = await http.post(f"{ADMIN}/bookings", json=payload(world, start, **extra))
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


async def test_phone_booking_creates_and_reuses_client(
    owner_client: httpx.AsyncClient, world: World, session: AsyncSession, clock: list[datetime]
) -> None:
    first = await create(owner_client, world, local(MONDAY, 12))
    assert first["source"] == "admin"
    assert first["status"] == "confirmed"
    assert first["client"]["phone"] == "+996700111222"
    second = await create(owner_client, world, local(MONDAY, 15))
    assert second["client"]["id"] == first["client"]["id"]
    assert await session.scalar(select(func.count()).select_from(Client)) == 1

    # offline barber is bookable by staff
    offline = await create(owner_client, world, local(MONDAY, 12), barber_id=str(world.second.id))
    assert offline["barber"]["id"] == str(world.second.id)


async def test_overlap_and_schedule_checks(
    owner_client: httpx.AsyncClient, world: World, clock: list[datetime]
) -> None:
    await create(owner_client, world, local(MONDAY, 12))
    overlap = await owner_client.post(
        f"{ADMIN}/bookings", json=payload(world, local(MONDAY, 12, 30))
    )
    assert overlap.status_code == 409
    assert overlap.json()["error"]["code"] == "slot_conflict"
    assert overlap.json()["error"]["details"]["alternatives"]

    late = await owner_client.post(f"{ADMIN}/bookings", json=payload(world, local(MONDAY, 20)))
    assert late.status_code == 409  # outside working hours
    forced = await owner_client.post(
        f"{ADMIN}/bookings", json=payload(world, local(MONDAY, 20), ignore_schedule=True)
    )
    assert forced.status_code == 201
    # overlaps are rejected even with ignore_schedule (DB constraint)
    forced_overlap = await owner_client.post(
        f"{ADMIN}/bookings", json=payload(world, local(MONDAY, 12, 30), ignore_schedule=True)
    )
    assert forced_overlap.status_code == 409


async def test_concurrent_bookings_exactly_one_succeeds(
    owner_client: httpx.AsyncClient, world: World, session: AsyncSession, clock: list[datetime]
) -> None:
    """Ten parallel requests for the same slot bypassing holds: the exclusion constraint
    lets exactly one through."""
    bodies = [
        payload(
            world,
            local(MONDAY, 14),
            client={"name": f"C{i}", "phone": f"+99670000{i:04d}"},
            ignore_schedule=True,
        )
        for i in range(10)
    ]
    responses = await asyncio.gather(
        *(owner_client.post(f"{ADMIN}/bookings", json=body) for body in bodies)
    )
    statuses = sorted(r.status_code for r in responses)
    assert statuses == [201] + [409] * 9, statuses
    assert await session.scalar(select(func.count()).select_from(Booking)) == 1


async def test_patch_services_and_prices(
    owner_client: httpx.AsyncClient, world: World, clock: list[datetime]
) -> None:
    booking = await create(owner_client, world, local(MONDAY, 12))
    patched = await owner_client.patch(
        f"{ADMIN}/bookings/{booking['id']}",
        json={
            "version": booking["version"],
            "services": [
                {"service_id": str(world.haircut.id), "price": 70_000},
                {"service_id": str(world.beard.id)},
            ],
            "admin_note": "скидка постоянному",
        },
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["subtotal"] == 120_000
    assert body["total_due"] == 120_000
    assert datetime.fromisoformat(body["end_at"]) == local(MONDAY, 13, 30)
    assert body["version"] == booking["version"] + 1

    stale = await owner_client.patch(
        f"{ADMIN}/bookings/{booking['id']}", json={"version": booking["version"], "comment": "x"}
    )
    assert stale.status_code == 412
    assert stale.json()["error"]["code"] == "version_mismatch"


async def test_patch_extending_into_next_booking_conflicts(
    owner_client: httpx.AsyncClient, world: World, clock: list[datetime]
) -> None:
    first = await create(owner_client, world, local(MONDAY, 12))
    await create(owner_client, world, local(MONDAY, 13))
    response = await owner_client.patch(
        f"{ADMIN}/bookings/{first['id']}",
        json={
            "version": first["version"],
            "services": [
                {"service_id": str(world.haircut.id)},
                {"service_id": str(world.beard.id)},
            ],
        },
    )
    assert response.status_code == 409


async def test_status_flow(
    owner_client: httpx.AsyncClient,
    world: World,
    session: AsyncSession,
    clock: list[datetime],
) -> None:
    booking = await create(owner_client, world, local(MONDAY, 12))
    url = f"{ADMIN}/bookings/{booking['id']}/status"

    early = await owner_client.post(
        url, json={"version": booking["version"], "status": "completed", "payment_method": "cash"}
    )
    assert early.json()["error"]["code"] == "booking_in_future"

    clock[0] = local(MONDAY, 13, 5)
    no_payment = await owner_client.post(
        url, json={"version": booking["version"], "status": "completed"}
    )
    assert no_payment.json()["error"]["code"] == "payment_required"

    done = await owner_client.post(
        url,
        json={
            "version": booking["version"],
            "status": "completed",
            "payment_method": "card",
            "paid_amount": 75_000,
        },
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed"
    assert done.json()["paid_amount"] == 75_000

    again = await owner_client.post(
        url, json={"version": done.json()["version"], "status": "cancelled"}
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "invalid_transition"

    audit = await session.scalar(select(AuditLog).where(AuditLog.action == "booking.status"))
    assert audit is not None
    assert audit.after is not None
    assert audit.after["paid_amount"] == 75_000


async def test_no_show_counter_and_admin_cancel_notifies(
    owner_client: httpx.AsyncClient, world: World, session: AsyncSession, clock: list[datetime]
) -> None:
    a = await create(owner_client, world, local(MONDAY, 12))
    b = await create(owner_client, world, local(MONDAY, 15))
    await owner_client.post(
        f"{ADMIN}/bookings/{a['id']}/status", json={"version": a["version"], "status": "no_show"}
    )
    client = await session.get(Client, a["client"]["id"])
    assert client is not None
    await session.refresh(client)
    assert client.no_show_count == 1

    cancelled = await owner_client.post(
        f"{ADMIN}/bookings/{b['id']}/status",
        json={"version": b["version"], "status": "cancelled", "reason": "мастер заболел"},
    )
    assert cancelled.json()["cancel_reason"] == "мастер заболел"


async def test_barber_can_complete_only_own(
    client: httpx.AsyncClient,
    owner_client: httpx.AsyncClient,
    world: World,
    make_admin: AdminFactory,
    app: FastAPI,
    clock: list[datetime],
) -> None:
    own = await create(owner_client, world, local(MONDAY, 12))
    other = await create(owner_client, world, local(MONDAY, 12), barber_id=str(world.second.id))
    clock[0] = local(MONDAY, 13, 30)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as barber:
        await login_as(barber, await make_admin(AdminRole.BARBER, barber_id=world.first.id))
        listed = await barber.get(f"{ADMIN}/bookings")
        assert [item["id"] for item in listed.json()["items"]] == [own["id"]]
        assert (await barber.get(f"{ADMIN}/bookings/{other['id']}")).status_code == 403

        body = {"version": own["version"], "status": "completed", "payment_method": "cash"}
        assert (
            await barber.post(f"{ADMIN}/bookings/{own['id']}/status", json=body)
        ).status_code == 200
        foreign = {"version": other["version"], "status": "completed", "payment_method": "cash"}
        response = await barber.post(f"{ADMIN}/bookings/{other['id']}/status", json=foreign)
        assert response.status_code == 403
        assert (
            await barber.post(f"{ADMIN}/bookings", json=payload(world, local(MONDAY, 16)))
        ).status_code == 403


async def test_move_drag_and_drop(
    owner_client: httpx.AsyncClient, world: World, session: AsyncSession, clock: list[datetime]
) -> None:
    booking = await create(owner_client, world, local(MONDAY, 12))
    await create(owner_client, world, local(MONDAY, 15))

    moved = await owner_client.post(
        f"{ADMIN}/bookings/{booking['id']}/move",
        json={
            "version": booking["version"],
            "start_at": local(MONDAY, 12, 30).isoformat(),
            "barber_id": str(world.second.id),
        },
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["barber"]["id"] == str(world.second.id)
    assert datetime.fromisoformat(moved.json()["end_at"]) == local(MONDAY, 13, 30)

    clash = await owner_client.post(
        f"{ADMIN}/bookings/{booking['id']}/move",
        json={
            "version": moved.json()["version"],
            "start_at": local(MONDAY, 14, 30).isoformat(),
            "barber_id": str(world.first.id),
        },
    )
    assert clash.status_code == 409

    templates = (await session.execute(select(TelegramOutbox.template_key))).scalars().all()
    assert "booking_rescheduled_client" not in templates  # phone client has no Telegram


async def test_blocks(owner_client: httpx.AsyncClient, world: World, clock: list[datetime]) -> None:
    block = await owner_client.post(
        f"{ADMIN}/blocks",
        json={
            "barber_id": str(world.first.id),
            "start_at": local(MONDAY, 13).isoformat(),
            "end_at": local(MONDAY, 14).isoformat(),
            "comment": "обед",
        },
    )
    assert block.status_code == 201
    assert block.json()["kind"] == "block"

    blocked = await owner_client.post(
        f"{ADMIN}/bookings", json=payload(world, local(MONDAY, 12, 30))
    )
    assert blocked.status_code == 409

    calendar = await owner_client.get(
        f"{ADMIN}/calendar", params={"date_from": str(MONDAY), "date_to": str(MONDAY)}
    )
    assert [item["kind"] for item in calendar.json()] == ["block"]

    assert (await owner_client.delete(f"{ADMIN}/blocks/{block.json()['id']}")).status_code == 204
    assert (
        await owner_client.post(f"{ADMIN}/bookings", json=payload(world, local(MONDAY, 12, 30)))
    ).status_code == 201


async def test_list_filters(
    owner_client: httpx.AsyncClient, world: World, clock: list[datetime]
) -> None:
    a = await create(owner_client, world, local(MONDAY, 12))
    await create(owner_client, world, local(MONDAY + timedelta(days=1), 12))
    await create(owner_client, world, local(MONDAY, 12), barber_id=str(world.second.id))

    by_day = await owner_client.get(
        f"{ADMIN}/bookings", params={"date_from": str(MONDAY), "date_to": str(MONDAY)}
    )
    assert by_day.json()["total"] == 2
    by_barber = await owner_client.get(
        f"{ADMIN}/bookings",
        params={"date_from": str(MONDAY), "date_to": str(MONDAY), "barber_id": str(world.first.id)},
    )
    assert [item["id"] for item in by_barber.json()["items"]] == [a["id"]]
    cancelled = await owner_client.get(f"{ADMIN}/bookings", params={"status": "cancelled"})
    assert cancelled.json()["total"] == 0


# ---------------------------------------------------------------------------
# notification feed
# ---------------------------------------------------------------------------


async def test_notification_feed(
    owner_client: httpx.AsyncClient,
    client: httpx.AsyncClient,
    world: World,
    make_admin: AdminFactory,
    app: FastAPI,
    clock: list[datetime],
) -> None:
    await create(owner_client, world, local(MONDAY, 12))
    await create(owner_client, world, local(MONDAY, 12), barber_id=str(world.second.id))

    feed = await owner_client.get(f"{ADMIN}/notifications")
    items = feed.json()
    assert [item["type"] for item in items] == ["booking_created", "booking_created"]
    assert all(item["read"] is False for item in items)
    assert (await owner_client.get(f"{ADMIN}/notifications/unread-count")).json() == {"unread": 2}

    assert (
        await owner_client.post(f"{ADMIN}/notifications/{items[0]['id']}/read")
    ).status_code == 204
    assert (await owner_client.get(f"{ADMIN}/notifications/unread-count")).json() == {"unread": 1}
    assert (await owner_client.post(f"{ADMIN}/notifications/read-all")).json() == {"marked": 1}
    assert (await owner_client.get(f"{ADMIN}/notifications/unread-count")).json() == {"unread": 0}

    since = await owner_client.get(
        f"{ADMIN}/notifications", params={"since": items[0]["created_at"]}
    )
    assert since.json() == []

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as barber:
        await login_as(barber, await make_admin(AdminRole.BARBER, barber_id=world.first.id))
        own = (await barber.get(f"{ADMIN}/notifications")).json()
        assert len(own) == 1
        assert own[0]["payload"]["barber_id"] == str(world.first.id)
        assert (await barber.get(f"{ADMIN}/notifications/unread-count")).json() == {"unread": 1}
