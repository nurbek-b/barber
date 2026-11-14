from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_now
from app.core.security.initdata import build_init_data
from app.models import (
    AuditLog,
    Barber,
    BarberSchedule,
    BarberService,
    Booking,
    Branch,
    Notification,
    SalonSettings,
    Service,
    TelegramOutbox,
)
from app.models.enums import BookingStatus
from tests.conftest import BOT_TOKEN, tma_header

TZ = ZoneInfo("Asia/Bishkek")
MONDAY = date(2026, 12, 7)
TUESDAY = MONDAY + timedelta(days=1)
MINI = "/api/v1/miniapp"


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
    w.first = Barber(branch_id=branch.id, name="Первый", sort_order=1, telegram_chat_id=777)
    w.second = Barber(branch_id=branch.id, name="Второй", sort_order=2)
    session.add_all([w.haircut, w.beard, w.first, w.second])
    await session.flush()
    session.add_all(
        [
            BarberService(barber_id=w.first.id, service_id=w.haircut.id, price=100_000),
            BarberService(barber_id=w.first.id, service_id=w.beard.id),
            BarberService(barber_id=w.second.id, service_id=w.haircut.id),
        ]
    )
    for barber in (w.first, w.second):
        for weekday in range(7):
            session.add(
                BarberSchedule(
                    barber_id=barber.id, weekday=weekday, start_time=time(10), end_time=time(19)
                )
            )
    salon = await session.get(SalonSettings, branch.id)
    assert salon is not None
    salon.admin_chat_id = -100123
    salon.notify_barbers = True
    await session.commit()
    return w


async def register(http: httpx.AsyncClient, telegram_id: int) -> dict[str, str]:
    headers = tma_header(telegram_id)
    contact = build_init_data(
        {
            "contact": json.dumps(
                {"user_id": telegram_id, "phone_number": f"99655500{telegram_id}"}
            ),
            "auth_date": str(int(datetime.now(UTC).timestamp())),
        },
        BOT_TOKEN,
    )
    response = await http.post(f"{MINI}/me/phone", headers=headers, json={"contact": contact})
    assert response.status_code == 200, response.text
    return headers


async def hold(
    http: httpx.AsyncClient,
    headers: dict[str, str],
    start: datetime,
    services: list[Service],
    barber: Barber | None = None,
    **extra: Any,
) -> httpx.Response:
    return await http.post(
        f"{MINI}/holds",
        headers=headers,
        json={
            "barber_id": str(barber.id) if barber else None,
            "service_ids": [str(s.id) for s in services],
            "start_at": start.isoformat(),
            **extra,
        },
    )


async def book(
    http: httpx.AsyncClient,
    headers: dict[str, str],
    hold_id: str,
    key: str | None = None,
    **body: Any,
) -> httpx.Response:
    return await http.post(
        f"{MINI}/bookings",
        headers={**headers, "Idempotency-Key": key or uuid.uuid4().hex},
        json={"hold_id": hold_id, **body},
    )


async def test_full_booking_flow(
    client: httpx.AsyncClient, world: World, session: AsyncSession, clock: list[datetime]
) -> None:
    headers = await register(client, 101)
    held = await hold(client, headers, local(MONDAY, 12), [world.haircut, world.beard], world.first)
    assert held.status_code == 201, held.text
    body = held.json()
    assert body["barber"]["id"] == str(world.first.id)
    assert body["quote"]["subtotal"] == 150_000  # barber price 100k + base 50k
    assert body["quote"]["duration_min"] == 90
    assert body["quote"]["max_bonus_spend"] == 0
    assert datetime.fromisoformat(body["end_at"]) == local(MONDAY, 13, 30)

    created = await book(client, headers, body["hold_id"], comment="Без бороды не уходить")
    assert created.status_code == 201, created.text
    booking = created.json()
    assert booking["status"] == "confirmed"
    assert booking["total_due"] == 150_000
    assert [s["price"] for s in booking["services"]] == [100_000, 50_000]
    assert booking["can_cancel"] is True

    # slot is gone for everybody
    slots = await client.get(
        f"{MINI}/availability/slots",
        headers=headers,
        params={
            "date": str(MONDAY),
            "barber_id": str(world.first.id),
            "service_ids": [str(world.beard.id)],
        },
    )
    starts = {datetime.fromisoformat(s["start_at"]) for s in slots.json()["slots"]}
    assert local(MONDAY, 12) not in starts
    assert local(MONDAY, 13, 30) in starts

    # side effects in the same transaction
    outbox = (await session.execute(select(TelegramOutbox))).scalars().all()
    templates = sorted(item.template_key for item in outbox)
    assert templates == [
        "booking_created_admin",
        "booking_created_barber",
        "booking_created_client",
    ]
    admin_msg = next(o for o in outbox if o.template_key == "booking_created_admin")
    assert admin_msg.chat_id == -100123
    assert admin_msg.payload["phone"] == "+99655500101"
    assert admin_msg.payload["when"] == "07.12.2026 12:00"
    assert admin_msg.payload["total_due_raw"] == 150_000
    assert await session.scalar(select(func.count()).select_from(Notification)) == 1
    assert (
        await session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "booking.create")
        )
        == 1
    )


async def test_any_barber_assigns_least_loaded(
    client: httpx.AsyncClient, world: World, clock: list[datetime]
) -> None:
    first_client = await register(client, 201)
    second_client = await register(client, 202)
    # first booking: both free → tie on load → sort_order → first barber
    one = await hold(client, first_client, local(MONDAY, 12), [world.haircut])
    assert one.json()["barber"]["id"] == str(world.first.id)
    assert (await book(client, first_client, one.json()["hold_id"])).status_code == 201
    # second booking at another time: first now has 60 booked minutes → second barber
    two = await hold(client, second_client, local(MONDAY, 15), [world.haircut])
    assert two.json()["barber"]["id"] == str(world.second.id)
    assert two.json()["quote"]["subtotal"] == 80_000


async def test_hold_blocks_other_clients(
    client: httpx.AsyncClient, world: World, clock: list[datetime]
) -> None:
    alice = await register(client, 301)
    bob = await register(client, 302)
    first = await hold(client, alice, local(MONDAY, 12), [world.beard], world.first)
    assert first.status_code == 201
    taken = await hold(client, bob, local(MONDAY, 12, 15), [world.beard], world.first)
    assert taken.status_code == 409
    error = taken.json()["error"]
    assert error["code"] == "slot_conflict"
    alternatives = [datetime.fromisoformat(s["start_at"]) for s in error["details"]["alternatives"]]
    assert alternatives
    assert local(MONDAY, 12) not in alternatives
    assert local(MONDAY, 12, 15) not in alternatives

    # Bob doesn't see Alice's held time, Alice still does
    params = {
        "date": str(MONDAY),
        "barber_id": str(world.first.id),
        "service_ids": [str(world.beard.id)],
    }
    bob_slots = await client.get(f"{MINI}/availability/slots", headers=bob, params=params)
    assert local(MONDAY, 12).isoformat().replace("+00:00", "Z") not in str(bob_slots.json())

    # Alice releases → Bob can hold
    await client.delete(f"{MINI}/holds/{first.json()['hold_id']}", headers=alice)
    again = await hold(client, bob, local(MONDAY, 12, 15), [world.beard], world.first)
    assert again.status_code == 201


async def test_new_hold_replaces_previous_one(
    client: httpx.AsyncClient, world: World, redis: FakeAsyncRedis, clock: list[datetime]
) -> None:
    alice = await register(client, 351)
    first = await hold(client, alice, local(MONDAY, 12), [world.beard], world.first)
    second = await hold(client, alice, local(MONDAY, 15), [world.beard], world.second)
    assert second.status_code == 422  # second barber doesn't do beards
    second = await hold(client, alice, local(MONDAY, 15), [world.haircut], world.second)
    assert second.status_code == 201
    assert await redis.get(f"hold:{first.json()['hold_id']}") is None
    assert await redis.zcard(f"holds:{world.first.id}") == 0


async def test_expired_hold(client: httpx.AsyncClient, world: World, clock: list[datetime]) -> None:
    alice = await register(client, 401)
    held = await hold(client, alice, local(MONDAY, 12), [world.beard], world.first)
    clock[0] = clock[0] + timedelta(minutes=6)
    response = await book(client, alice, held.json()["hold_id"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "hold_expired"


async def test_foreign_hold_cannot_be_used(
    client: httpx.AsyncClient, world: World, clock: list[datetime]
) -> None:
    alice = await register(client, 451)
    mallory = await register(client, 452)
    held = await hold(client, alice, local(MONDAY, 12), [world.beard], world.first)
    response = await book(client, mallory, held.json()["hold_id"])
    assert response.json()["error"]["code"] == "hold_expired"


async def test_idempotent_retry_returns_same_booking(
    client: httpx.AsyncClient, world: World, session: AsyncSession, clock: list[datetime]
) -> None:
    alice = await register(client, 501)
    held = await hold(client, alice, local(MONDAY, 12), [world.beard], world.first)
    key = uuid.uuid4().hex
    first = await book(client, alice, held.json()["hold_id"], key)
    retry = await book(client, alice, held.json()["hold_id"], key)
    assert first.status_code == 201
    assert retry.status_code == 200
    assert retry.json()["id"] == first.json()["id"]
    assert await session.scalar(select(func.count()).select_from(Booking)) == 1

    mismatch = await book(client, alice, held.json()["hold_id"], key, comment="другое")
    assert mismatch.status_code == 422
    assert mismatch.json()["error"]["code"] == "idempotency_mismatch"


async def test_concurrent_retries_with_same_key(
    client: httpx.AsyncClient,
    world: World,
    session: AsyncSession,
    redis: FakeAsyncRedis,
    clock: list[datetime],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redis guard wiped (e.g. restart): the DB unique index still dedupes parallel retries."""
    alice = await register(client, 551)
    held = await hold(client, alice, local(MONDAY, 12), [world.beard], world.first)
    key = uuid.uuid4().hex
    original_set = redis.set

    async def no_guard(name: str, *args: Any, **kwargs: Any) -> Any:
        if str(name).startswith("idem:"):
            return True
        return await original_set(name, *args, **kwargs)

    monkeypatch.setattr(redis, "set", no_guard)
    try:
        responses = await asyncio.gather(
            *(book(client, alice, held.json()["hold_id"], key) for _ in range(5))
        )
    finally:
        monkeypatch.undo()
    statuses = sorted(r.status_code for r in responses)
    ok = [r for r in responses if r.status_code in (200, 201)]
    assert len({r.json()["id"] for r in ok}) == 1, statuses
    assert await session.scalar(select(func.count()).select_from(Booking)) == 1


async def test_phone_is_required(
    client: httpx.AsyncClient, world: World, clock: list[datetime]
) -> None:
    headers = tma_header(601)
    held = await hold(client, headers, local(MONDAY, 12), [world.beard], world.first)
    response = await book(client, headers, held.json()["hold_id"])
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "phone_required"


async def test_max_active_bookings(
    client: httpx.AsyncClient, world: World, clock: list[datetime]
) -> None:
    alice = await register(client, 651)
    for hour in (11, 13, 15):  # default limit = 3
        held = await hold(client, alice, local(TUESDAY, hour), [world.beard], world.first)
        assert (await book(client, alice, held.json()["hold_id"])).status_code == 201
    held = await hold(client, alice, local(TUESDAY, 17), [world.beard], world.first)
    response = await book(client, alice, held.json()["hold_id"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "too_many_bookings"


async def test_booking_rate_limit(
    client: httpx.AsyncClient,
    world: World,
    session: AsyncSession,
    branch: Branch,
    clock: list[datetime],
) -> None:
    salon = await session.get(SalonSettings, branch.id)
    assert salon is not None
    salon.max_active_bookings_per_client = 50
    await session.commit()
    alice = await register(client, 671)
    statuses = []
    for index in range(6):
        held = await hold(
            client, alice, local(TUESDAY, 10) + timedelta(hours=index), [world.beard], world.first
        )
        statuses.append((await book(client, alice, held.json()["hold_id"])).status_code)
    assert statuses == [201] * 5 + [429]


async def test_bonus_above_limit_rejected(
    client: httpx.AsyncClient, world: World, clock: list[datetime]
) -> None:
    alice = await register(client, 681)
    held = await hold(client, alice, local(MONDAY, 12), [world.beard], world.first)
    response = await book(client, alice, held.json()["hold_id"], bonus_to_spend=1)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "bonus_limit"


async def test_db_conflict_returns_409_with_alternatives(
    client: httpx.AsyncClient,
    world: World,
    session: AsyncSession,
    redis: FakeAsyncRedis,
    branch: Branch,
    clock: list[datetime],
) -> None:
    """Hold says free, but a booking appeared directly in the DB (e.g. by staff) and the
    cache hasn't caught up — the exclusion constraint must catch it."""
    alice = await register(client, 701)
    held = await hold(client, alice, local(MONDAY, 12), [world.beard], world.first)

    from app.cli import init_salon  # noqa: F401  (branch already exists)

    other = Booking(
        branch_id=branch.id,
        client_id=(await client.get(f"{MINI}/me", headers=alice)).json()["id"],
        barber_id=world.first.id,
        start_at=local(MONDAY, 12),
        end_at=local(MONDAY, 12, 30),
        blocked_until=local(MONDAY, 12, 30),
        subtotal=1,
        bonus_spent=0,
        total_due=1,
    )
    session.add(other)
    await session.commit()

    response = await book(client, alice, held.json()["hold_id"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "slot_conflict"
    assert response.json()["error"]["details"]["alternatives"]


async def test_concurrent_holds_exactly_one_wins(
    client: httpx.AsyncClient, world: World, clock: list[datetime]
) -> None:
    clients = [await register(client, 800 + index) for index in range(10)]
    responses = await asyncio.gather(
        *(
            hold(client, headers, local(MONDAY, 12), [world.beard], world.first)
            for headers in clients
        )
    )
    statuses = sorted(r.status_code for r in responses)
    assert statuses == [201] + [409] * 9


# ---------------------------------------------------------------------------
# my bookings, cancel, reschedule, repeat
# ---------------------------------------------------------------------------


async def _booked(
    http: httpx.AsyncClient, headers: dict[str, str], world: World, start: datetime
) -> dict[str, Any]:
    held = await hold(http, headers, start, [world.beard], world.first)
    created = await book(http, headers, held.json()["hold_id"])
    assert created.status_code == 201, created.text
    result: dict[str, Any] = created.json()
    return result


async def test_list_and_idor(
    client: httpx.AsyncClient, world: World, clock: list[datetime]
) -> None:
    alice = await register(client, 901)
    eve = await register(client, 902)
    first = await _booked(client, alice, world, local(TUESDAY, 12))
    second = await _booked(client, alice, world, local(MONDAY, 15))

    page = await client.get(f"{MINI}/bookings", headers=alice, params={"limit": 1})
    assert [item["id"] for item in page.json()["items"]] == [second["id"]]
    cursor = page.json()["next_cursor"]
    rest = await client.get(
        f"{MINI}/bookings", headers=alice, params={"limit": 1, "cursor": cursor}
    )
    assert [item["id"] for item in rest.json()["items"]] == [first["id"]]
    assert rest.json()["next_cursor"] is None

    assert (await client.get(f"{MINI}/bookings/{first['id']}", headers=eve)).status_code == 404
    cancel = await client.post(f"{MINI}/bookings/{first['id']}/cancel", headers=eve, json={})
    assert cancel.status_code == 404
    assert (await client.get(f"{MINI}/bookings", headers=eve)).json()["items"] == []


async def test_cancel_rules(
    client: httpx.AsyncClient, world: World, session: AsyncSession, clock: list[datetime]
) -> None:
    alice = await register(client, 951)
    soon = await _booked(client, alice, world, local(MONDAY, 10))  # cancel_min_hours = 2
    later = await _booked(client, alice, world, local(MONDAY, 15))
    clock[0] = local(MONDAY, 8, 30)  # 1.5 h before the 10:00 booking

    too_late = await client.post(f"{MINI}/bookings/{soon['id']}/cancel", headers=alice, json={})
    assert too_late.status_code == 422
    assert too_late.json()["error"]["code"] == "cancel_too_late"

    done = await client.post(
        f"{MINI}/bookings/{later['id']}/cancel", headers=alice, json={"reason": "заболел"}
    )
    assert done.status_code == 200
    assert done.json()["status"] == "cancelled"
    assert done.json()["can_cancel"] is False
    again = await client.post(f"{MINI}/bookings/{later['id']}/cancel", headers=alice, json={})
    assert again.json()["error"]["code"] == "booking_not_active"

    past = await client.get(f"{MINI}/bookings", headers=alice, params={"scope": "past"})
    assert [item["id"] for item in past.json()["items"]] == [later["id"]]

    outbox = (await session.execute(select(TelegramOutbox.template_key))).scalars().all()
    assert "booking_cancelled_admin" in outbox
    assert "booking_cancelled_client" in outbox


async def test_reschedule(
    client: httpx.AsyncClient, world: World, session: AsyncSession, clock: list[datetime]
) -> None:
    alice = await register(client, 961)
    booking = await _booked(client, alice, world, local(MONDAY, 15))
    # overlapping move by 15 minutes must be possible (the booking itself is excluded)
    held = await hold(
        client,
        alice,
        local(MONDAY, 15, 15),
        [world.beard],
        world.first,
        reschedule_booking_id=booking["id"],
    )
    assert held.status_code == 201, held.text
    moved = await client.post(
        f"{MINI}/bookings/{booking['id']}/reschedule",
        headers=alice,
        json={"hold_id": held.json()["hold_id"]},
    )
    assert moved.status_code == 200, moved.text
    assert datetime.fromisoformat(moved.json()["start_at"]) == local(MONDAY, 15, 15)
    assert datetime.fromisoformat(moved.json()["end_at"]) == local(MONDAY, 15, 45)

    notification = await session.scalar(
        select(Notification).where(Notification.type == "booking_rescheduled")
    )
    assert notification is not None
    assert notification.payload["old_when"] == "07.12.2026 15:00"

    wrong = await hold(
        client,
        alice,
        local(MONDAY, 17),
        [world.haircut],
        world.first,
        reschedule_booking_id=booking["id"],
    )
    mismatch = await client.post(
        f"{MINI}/bookings/{booking['id']}/reschedule",
        headers=alice,
        json={"hold_id": wrong.json()["hold_id"]},
    )
    assert mismatch.json()["error"]["code"] == "hold_services_mismatch"


async def test_repeat_last_visit(
    client: httpx.AsyncClient, world: World, session: AsyncSession, clock: list[datetime]
) -> None:
    alice = await register(client, 971)
    assert (await client.get(f"{MINI}/bookings/repeat", headers=alice)).json() is None
    booking = await _booked(client, alice, world, local(MONDAY, 12))
    row = await session.get(Booking, uuid.UUID(booking["id"]))
    assert row is not None
    row.status = BookingStatus.COMPLETED
    await session.commit()
    clock[0] = local(TUESDAY, 9)

    draft = await client.get(f"{MINI}/bookings/repeat", headers=alice)
    body = draft.json()
    assert body["source_booking_id"] == booking["id"]
    assert body["barber"]["id"] == str(world.first.id)
    assert body["service_ids"] == [str(world.beard.id)]
    assert body["missing_service_ids"] == []
