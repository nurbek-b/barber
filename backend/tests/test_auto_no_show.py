from __future__ import annotations

from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import AuditLog, Booking, Client, SalonSettings, TelegramOutbox
from app.models.enums import BookingStatus
from app.worker.no_show import mark_no_shows
from tests.test_bookings_admin import (  # noqa: F401 - pytest fixtures
    ADMIN,
    MONDAY,
    World,
    clock,
    create,
    local,
    world,
)


async def _salon(session: AsyncSession) -> SalonSettings:
    salon = await session.scalar(select(SalonSettings))
    assert salon is not None
    return salon


async def test_unclosed_visit_becomes_auto_no_show_and_admin_can_fix_it(
    owner_client: httpx.AsyncClient,
    world: World,  # noqa: F811
    session: AsyncSession,
    maker: async_sessionmaker[AsyncSession],
    clock: list[datetime],  # noqa: F811
) -> None:
    salon = await _salon(session)
    salon.admin_chat_id = -100500
    await session.commit()
    booking = await create(owner_client, world, local(MONDAY, 12))
    end = datetime.fromisoformat(booking["end_at"])

    # default: 3 hours after the end
    assert await mark_no_shows(maker, None, end + timedelta(hours=2, minutes=59)) == 0
    assert await mark_no_shows(maker, None, end + timedelta(hours=3, minutes=1)) == 1
    assert await mark_no_shows(maker, None, end + timedelta(hours=3, minutes=2)) == 0

    stored = await session.get(Booking, booking["id"])
    assert stored is not None
    await session.refresh(stored)
    assert (stored.status, stored.no_show_auto) == (BookingStatus.NO_SHOW, True)
    client = await session.get(Client, booking["client"]["id"])
    assert client is not None
    await session.refresh(client)
    assert client.no_show_count == 1
    templates = await session.scalars(
        select(TelegramOutbox.template_key).where(TelegramOutbox.booking_id == stored.id)
    )
    assert "booking_auto_no_show_admin" in list(templates)

    view = (await owner_client.get(f"{ADMIN}/bookings/{booking['id']}")).json()
    assert (view["status"], view["no_show_auto"]) == ("no_show", True)

    # "the client did come": straight to completed, the no-show is taken back
    clock[0] = end + timedelta(hours=4)
    came = await owner_client.post(
        f"{ADMIN}/bookings/{booking['id']}/status",
        json={
            "version": view["version"],
            "status": "completed",
            "payment_method": "cash",
            "paid_amount": view["subtotal"],
        },
    )
    assert came.status_code == 200, came.text
    assert (came.json()["status"], came.json()["no_show_auto"]) == ("completed", False)
    await session.refresh(client)
    assert (client.no_show_count, client.visits_count) == (0, 1)


async def test_salon_confirms_auto_no_show(
    owner_client: httpx.AsyncClient,
    world: World,  # noqa: F811
    session: AsyncSession,
    maker: async_sessionmaker[AsyncSession],
    clock: list[datetime],  # noqa: F811
) -> None:
    booking = await create(owner_client, world, local(MONDAY, 12))
    end = datetime.fromisoformat(booking["end_at"])
    assert await mark_no_shows(maker, None, end + timedelta(hours=3, minutes=1)) == 1
    view = (await owner_client.get(f"{ADMIN}/bookings/{booking['id']}")).json()

    url = f"{ADMIN}/bookings/{booking['id']}/status"
    confirmed = await owner_client.post(url, json={"version": view["version"], "status": "no_show"})
    assert confirmed.status_code == 200, confirmed.text
    assert (confirmed.json()["status"], confirmed.json()["no_show_auto"]) == ("no_show", False)
    audit = await session.scalar(
        select(AuditLog).where(AuditLog.action == "booking.no_show_confirmed")
    )
    assert audit is not None
    client = await session.get(Client, booking["client"]["id"])
    assert client is not None
    await session.refresh(client)
    assert client.no_show_count == 1  # confirming does not count twice

    again = await owner_client.post(
        url, json={"version": confirmed.json()["version"], "status": "no_show"}
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "invalid_transition"


async def test_auto_no_show_off_and_old_visits_untouched(
    owner_client: httpx.AsyncClient,
    world: World,  # noqa: F811
    session: AsyncSession,
    maker: async_sessionmaker[AsyncSession],
    clock: list[datetime],  # noqa: F811
) -> None:
    booking = await create(owner_client, world, local(MONDAY, 12))
    end = datetime.fromisoformat(booking["end_at"])
    # an old open visit is history: turning the feature on does not rewrite it
    assert await mark_no_shows(maker, None, end + timedelta(days=2)) == 0

    current = (await owner_client.get(f"{ADMIN}/settings/salon")).json()
    saved = await owner_client.put(
        f"{ADMIN}/settings/salon", json={**current, "auto_no_show_hours": 0}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["auto_no_show_hours"] == 0
    assert await mark_no_shows(maker, None, end + timedelta(hours=4)) == 0
    stored = await session.get(Booking, booking["id"])
    assert stored is not None
    await session.refresh(stored)
    assert stored.status is BookingStatus.CONFIRMED
