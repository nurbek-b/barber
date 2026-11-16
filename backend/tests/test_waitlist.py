"""Waitlist: full working days vs days off, joining, and messages when a slot frees up."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Barber,
    BarberSchedule,
    BarberService,
    Booking,
    BookingService,
    Branch,
    Client,
    Service,
    TelegramOutbox,
    WaitlistEntry,
)
from app.models.enums import BookingStatus
from tests.conftest import tma_header

MINI = "/api/v1/miniapp"
TZ = ZoneInfo("Asia/Bishkek")


async def _world(session: AsyncSession, branch: Branch) -> tuple[Barber, Service]:
    service = Service(
        branch_id=branch.id, name_i18n={"ru": "Стрижка"}, duration_min=60, base_price=1
    )
    barber = Barber(branch_id=branch.id, name="Азамат")
    session.add_all([service, barber])
    await session.flush()
    session.add(BarberService(barber_id=barber.id, service_id=service.id))
    # works every day except Sunday
    session.add_all(
        BarberSchedule(barber_id=barber.id, weekday=d, start_time=time(10), end_time=time(19))
        for d in range(6)
    )
    await session.commit()
    return barber, service


async def _client(http: httpx.AsyncClient, session: AsyncSession, tg: int) -> Client:
    me = await http.get(f"{MINI}/me", headers=tma_header(tg))
    found = await session.get(Client, me.json()["id"])
    assert found is not None
    return found


async def test_days_tell_day_off_from_fully_booked(
    client: httpx.AsyncClient, session: AsyncSession, branch: Branch
) -> None:
    barber, service = await _world(session, branch)
    days = (
        await client.get(
            f"{MINI}/availability/days",
            headers=tma_header(),
            params={"barber_id": str(barber.id), "service_ids": [str(service.id)]},
        )
    ).json()["days"]
    by_weekday = {datetime.fromisoformat(d["date"]).weekday(): d["working"] for d in days}
    assert by_weekday[6] is False  # Sunday: day off
    assert by_weekday[2] is True


async def test_join_list_leave(
    client: httpx.AsyncClient, session: AsyncSession, branch: Branch
) -> None:
    barber, service = await _world(session, branch)
    headers = tma_header(5001)
    day = (datetime.now(TZ) + timedelta(days=3)).date()
    body = {"barber_id": str(barber.id), "day": day.isoformat(), "service_ids": [str(service.id)]}
    first = await client.post(f"{MINI}/waitlist", headers=headers, json=body)
    assert first.status_code == 201, first.text
    assert first.json()["barber_name"] == "Азамат"
    again = await client.post(f"{MINI}/waitlist", headers=headers, json=body)
    assert again.json()["id"] == first.json()["id"], "no duplicates"

    past = {**body, "day": (day - timedelta(days=10)).isoformat()}
    assert (await client.post(f"{MINI}/waitlist", headers=headers, json=past)).status_code == 422

    for offset in range(1, 5):  # any barber, other days: 5 active in total
        extra = {"day": (day + timedelta(days=offset)).isoformat()}
        assert (
            await client.post(f"{MINI}/waitlist", headers=headers, json=extra)
        ).status_code == 201
    full = {"day": (day + timedelta(days=6)).isoformat()}
    too_many = await client.post(f"{MINI}/waitlist", headers=headers, json=full)
    assert too_many.json()["error"]["code"] == "waitlist_full"

    listed = (await client.get(f"{MINI}/waitlist", headers=headers)).json()
    assert len(listed) == 5
    deleted = await client.delete(f"{MINI}/waitlist/{first.json()['id']}", headers=headers)
    assert deleted.status_code == 204
    foreign = await client.delete(f"{MINI}/waitlist/{listed[1]['id']}", headers=tma_header(5002))
    assert foreign.status_code == 404


async def test_cancel_notifies_waiting_clients_once(
    client: httpx.AsyncClient, session: AsyncSession, branch: Branch
) -> None:
    barber, _service = await _world(session, branch)
    start = datetime.now(UTC) + timedelta(days=3)
    while start.astimezone(TZ).weekday() == 6:  # a working day
        start += timedelta(days=1)
    day = start.astimezone(TZ).date()

    holder = await _client(client, session, 6001)
    waiting = await _client(client, session, 6002)
    any_barber = await _client(client, session, 6003)
    other_day = await _client(client, session, 6004)
    for who, payload in (
        (6002, {"barber_id": str(barber.id), "day": day.isoformat()}),
        (6003, {"day": day.isoformat()}),
        (6004, {"barber_id": str(barber.id), "day": (day + timedelta(days=1)).isoformat()}),
    ):
        response = await client.post(f"{MINI}/waitlist", headers=tma_header(who), json=payload)
        assert response.status_code == 201

    booking = Booking(
        branch_id=branch.id,
        client_id=holder.id,
        barber_id=barber.id,
        status=BookingStatus.CONFIRMED,
        start_at=start,
        end_at=start + timedelta(hours=1),
        blocked_until=start + timedelta(hours=1),
        subtotal=1,
        bonus_spent=0,
        total_due=1,
        services=[BookingService(name_snapshot={"ru": "Стрижка"}, duration_min=60, price=1)],
    )
    session.add(booking)
    await session.commit()

    cancel = await client.post(
        f"{MINI}/bookings/{booking.id}/cancel", headers=tma_header(6001), json={}
    )
    assert cancel.status_code == 200, cancel.text

    rows = (
        (
            await session.execute(
                select(TelegramOutbox).where(TelegramOutbox.template_key == "waitlist_client")
            )
        )
        .scalars()
        .all()
    )
    assert sorted(row.chat_id for row in rows) == [6002, 6003]
    by_chat = {row.chat_id: row.payload["buttons"][0][0] for row in rows}
    link = by_chat[6002].get("web_app") or by_chat[6002].get("url")
    assert link.endswith(f"startapp=barber_{barber.id}")
    assert (by_chat[6003].get("web_app") or by_chat[6003].get("url")).endswith("startapp=book")

    entries = (await session.execute(select(WaitlistEntry))).scalars().all()
    notified = {entry.client_id for entry in entries if entry.notified_at is not None}
    assert notified == {waiting.id, any_barber.id}
    assert other_day.id not in notified
