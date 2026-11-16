"""Gift certificates and subscriptions: sale, applying to bookings, undo, release on cancel."""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Booking, Client
from app.services.vouchers import new_code, normalize_code
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

ADMIN = "/api/v1/admin"
PUBLIC = "/api/v1/public"


def test_codes() -> None:
    code = new_code()
    assert code.startswith("GIFT-")
    assert len(code) == 14
    assert normalize_code(" gift-ab cd-efgh ") == "GIFT-ABCD-EFGH"


async def _booking(
    client: httpx.AsyncClient,
    world: World,  # noqa: F811
    telegram_id: int,
    hour: int,
) -> tuple[dict[str, str], dict[str, object]]:
    headers = await register(client, telegram_id)
    held = (await hold(client, headers, local(MONDAY, hour), [world.haircut], world.first)).json()
    created = await book(client, headers, held["hold_id"])
    assert created.status_code == 201, created.text
    return headers, created.json()


async def _admin_booking(owner: httpx.AsyncClient, booking_id: object) -> dict[str, object]:
    return (await owner.get(f"{ADMIN}/bookings/{booking_id}")).json()


async def test_certificate_flow(
    client: httpx.AsyncClient,
    owner_client: httpx.AsyncClient,
    session: AsyncSession,
    world: World,  # noqa: F811
    clock: list[datetime],  # noqa: F811
) -> None:
    sold = await owner_client.post(
        f"{ADMIN}/certificates",
        json={"amount": 70_000, "recipient_name": "Айбек", "payment_method": "card"},
    )
    assert sold.status_code == 201, sold.text
    cert = sold.json()
    assert (cert["balance"], cert["state"]) == (70_000, "active")

    balance = (await client.get(f"{PUBLIC}/certificates/{cert['code'].lower()}")).json()
    assert (balance["balance"], balance["state"]) == (70_000, "active")
    assert (await client.get(f"{PUBLIC}/certificates/GIFT-NOPE-NOPE")).status_code == 404

    _, booking = await _booking(client, world, 9300, 12)
    url = f"{ADMIN}/bookings/{booking['id']}/vouchers"
    applied = await owner_client.post(f"{url}/certificate", json={"code": cert["code"]})
    assert applied.status_code == 200, applied.text
    assert [(u["kind"], u["amount"]) for u in applied.json()] == [("certificate", 70_000)]
    assert (await _admin_booking(owner_client, booking["id"]))["voucher_amount"] == 70_000
    empty = await owner_client.post(f"{url}/certificate", json={"code": cert["code"]})
    assert empty.json()["error"]["code"] == "certificate_used"

    # undo returns the balance; apply part of it again
    assert (
        await owner_client.delete(f"{ADMIN}/vouchers/{applied.json()[0]['id']}")
    ).status_code == 204
    partial = await owner_client.post(
        f"{url}/certificate", json={"code": cert["code"], "amount": 30_000}
    )
    assert partial.json()[0]["amount"] == 30_000

    # completion: the client pays the rest with money
    clock[0] = local(MONDAY, 14)
    current = await _admin_booking(owner_client, booking["id"])
    done = await owner_client.post(
        f"{ADMIN}/bookings/{booking['id']}/status",
        json={"version": current["version"], "status": "completed", "payment_method": "cash"},
    )
    assert done.status_code == 200, done.text
    assert done.json()["paid_amount"] == current["total_due"] - 30_000
    left = (
        await owner_client.get(f"{ADMIN}/certificates/lookup", params={"code": cert["code"]})
    ).json()
    assert left["balance"] == 40_000


@pytest.mark.usefixtures("clock")
async def test_subscription_flow(
    client: httpx.AsyncClient,
    owner_client: httpx.AsyncClient,
    session: AsyncSession,
    world: World,  # noqa: F811
) -> None:
    plan = await owner_client.post(
        f"{ADMIN}/subscription-plans",
        json={
            "name": "5 стрижек",
            "service_ids": [str(world.haircut.id)],
            "visits": 5,
            "price": 400_000,
            "valid_days": 90,
        },
    )
    assert plan.status_code == 201, plan.text
    headers, booking = await _booking(client, world, 9301, 12)
    me = await session.scalar(select(Client).where(Client.phone.like("%9301")))
    assert me is not None

    sold = await owner_client.post(
        f"{ADMIN}/subscriptions", json={"client_id": str(me.id), "plan_id": plan.json()["id"]}
    )
    assert sold.status_code == 201, sold.text
    sub = sold.json()
    assert (sub["visits_left"], sub["state"], sub["client_name"]) == (5, "active", me.name)

    url = f"{ADMIN}/bookings/{booking['id']}/vouchers/subscription"
    applied = await owner_client.post(url, json={"subscription_id": sub["id"]})
    assert applied.status_code == 200, applied.text
    covered = applied.json()[0]["amount"]
    assert covered == booking["total_due"]
    again = await owner_client.post(url, json={"subscription_id": sub["id"]})
    assert again.json()["error"]["code"] == "subscription_applied"

    mine = (await client.get(f"{MINI}/subscriptions", headers=headers)).json()
    assert [(s["name"], s["visits_left"]) for s in mine] == [("5 стрижек", 4)]

    # the client cancels: the visit comes back
    cancel = await client.post(f"{MINI}/bookings/{booking['id']}/cancel", headers=headers, json={})
    assert cancel.status_code == 200, cancel.text
    mine = (await client.get(f"{MINI}/subscriptions", headers=headers)).json()
    assert mine[0]["visits_left"] == 5
    stored = await session.get(Booking, booking["id"])
    assert stored is not None
    await session.refresh(stored)
    assert stored.voucher_amount == 0
