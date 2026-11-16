"""Public web booking: no Telegram, pending until the salon confirms, no data leaks by phone."""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Booking, Client, TelegramOutbox
from app.models.enums import BookingSource, BookingStatus
from tests.test_bookings_miniapp import (  # noqa: F401 - pytest fixtures
    MINI,
    MONDAY,
    World,
    book,
    clock,
    hold,
    local,
    register,
    world,
)

PUB = "/api/v1/public"


def _hold_body(world: World, hour: int, phone: str = "0700 123 456", **extra: object) -> dict:  # noqa: F811
    return {
        "name": "Айбек",
        "phone": phone,
        "barber_id": str(world.first.id),
        "service_ids": [str(world.haircut.id)],
        "start_at": local(MONDAY, hour).isoformat(),
        **extra,
    }


async def _confirm(http: httpx.AsyncClient, token: str, **extra: object) -> httpx.Response:
    return await http.post(
        f"{PUB}/bookings",
        headers={"Idempotency-Key": uuid.uuid4().hex},
        json={"token": token, **extra},
    )


@pytest.mark.usefixtures("clock")
async def test_catalog_is_public(client: httpx.AsyncClient, world: World) -> None:  # noqa: F811
    assert (await client.get(f"{PUB}/salon")).status_code == 200
    names = [b["name"] for b in (await client.get(f"{PUB}/barbers")).json()]
    assert names == ["Первый", "Второй"]
    services = (await client.get(f"{PUB}/services")).json()["services"]
    assert len(services) == 2
    days = await client.get(
        f"{PUB}/availability/days", params={"service_ids": [str(world.haircut.id)]}
    )
    assert days.status_code == 200
    # the Mini App API still requires Telegram
    assert (await client.get(f"{MINI}/salon")).status_code == 401


@pytest.mark.usefixtures("clock")
async def test_web_booking_is_pending_and_private(
    client: httpx.AsyncClient,
    session: AsyncSession,
    world: World,  # noqa: F811
) -> None:
    # someone already has an account with this phone in the Mini App (and bonuses)
    await register(client, 7)
    owner = (await session.execute(select(Client).where(Client.phone == "+996555007"))).scalar_one()
    owner.bonus_balance = 50_000
    await session.commit()

    held = await client.post(f"{PUB}/holds", json=_hold_body(world, 12, phone="+996 555 007"))
    assert held.status_code == 201, held.text
    body = held.json()
    assert body["quote"]["bonus_balance"] == 0, "bonuses of the phone's owner are not revealed"
    assert body["quote"]["max_bonus_spend"] == 0

    created = await _confirm(client, body["token"], comment="Можно пораньше?")
    assert created.status_code == 201, created.text
    booking = created.json()
    assert booking["status"] == "pending"
    assert set(booking) == {
        "id",
        "status",
        "barber",
        "services",
        "start_at",
        "end_at",
        "subtotal",
        "discount",
        "total_due",
    }

    stored = (
        await session.execute(select(Booking).where(Booking.id == booking["id"]))
    ).scalar_one()
    assert stored.source is BookingSource.WEB
    assert stored.status is BookingStatus.PENDING
    assert stored.client_id == owner.id
    assert stored.bonus_spent == 0

    outbox = (await session.execute(select(TelegramOutbox))).scalars().all()
    chats = {row.chat_id for row in outbox if row.template_key.startswith("booking_created")}
    assert -100123 in chats, "the salon's admin chat hears about it"
    assert 7 not in chats, "the phone's owner gets nothing: the number is not verified"


@pytest.mark.usefixtures("clock")
async def test_new_client_and_guards(
    client: httpx.AsyncClient,
    session: AsyncSession,
    world: World,  # noqa: F811
) -> None:
    bot = await client.post(f"{PUB}/holds", json=_hold_body(world, 12, website="http://spam"))
    assert bot.status_code == 422

    held = (await client.post(f"{PUB}/holds", json=_hold_body(world, 13))).json()
    forged = await _confirm(client, held["token"] + "x")
    assert forged.status_code == 401

    promo = await client.post(f"{PUB}/holds/promo", json={"token": held["token"], "code": "NONE"})
    assert promo.json()["error"]["code"] == "promo_not_found"

    created = await _confirm(client, held["token"])
    assert created.status_code == 201
    new_client = (
        await session.execute(select(Client).where(Client.phone == "+0700123456"))
    ).scalar_one()
    assert new_client.user_id is None

    # the same slot can't be taken twice
    again = await client.post(f"{PUB}/holds", json=_hold_body(world, 13, phone="0700999888"))
    assert again.status_code == 409
