"""Promo codes: admin management, rules, discount in the booking, uses given back on cancel."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.pricing import build_quote, promo_discount
from app.models import Booking
from app.models.enums import BookingStatus
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


def test_discount_math() -> None:
    assert promo_discount("percent", 2000, None, 100_000) == 20_000
    assert promo_discount("percent", 2000, 15_000, 100_000) == 15_000
    assert promo_discount("fixed", 30_000, None, 100_000) == 30_000
    assert promo_discount("fixed", 300_000, None, 100_000) == 100_000, "never above the check"
    quote = build_quote([], bonus_balance=0, max_spend_bp=0, bonus_enabled=False, discount=5)
    assert quote.discount == 0, "nothing to discount"


async def _create(http: httpx.AsyncClient, **fields: object) -> dict[str, object]:
    body = {"code": "spring20", "kind": "percent", "value": 2000, **fields}
    response = await http.post(f"{ADMIN}/promo-codes", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def test_admin_manages_codes(owner_client: httpx.AsyncClient) -> None:
    created = await _create(owner_client, max_discount=15_000, description="Весна")
    assert created["code"] == "SPRING20"
    duplicate = await owner_client.post(
        f"{ADMIN}/promo-codes", json={"code": "Spring20", "kind": "fixed", "value": 100}
    )
    assert duplicate.status_code == 409
    too_much = await owner_client.post(
        f"{ADMIN}/promo-codes", json={"code": "HALF", "kind": "percent", "value": 10_001}
    )
    assert too_much.status_code == 422
    bad = await owner_client.post(
        f"{ADMIN}/promo-codes", json={"code": "a b", "kind": "fixed", "value": 1}
    )
    assert bad.status_code == 422
    patched = await owner_client.patch(
        f"{ADMIN}/promo-codes/{created['id']}", json={"is_active": False}
    )
    assert patched.json()["is_active"] is False
    listed = (await owner_client.get(f"{ADMIN}/promo-codes")).json()
    assert [(item["code"], item["uses"]) for item in listed] == [("SPRING20", 0)]


@pytest.mark.usefixtures("clock")
async def test_promo_in_booking(
    client: httpx.AsyncClient,
    owner_client: httpx.AsyncClient,
    session: AsyncSession,
    world: World,  # noqa: F811
) -> None:
    promo = await _create(owner_client, max_discount=15_000)
    headers = await register(client, 9100)

    held = (await hold(client, headers, local(MONDAY, 12), [world.haircut], world.first)).json()
    unknown = await client.post(
        f"{MINI}/holds/{held['hold_id']}/promo", headers=headers, json={"code": "nope"}
    )
    assert unknown.json()["error"]["code"] == "promo_not_found"
    checked = await client.post(
        f"{MINI}/holds/{held['hold_id']}/promo", headers=headers, json={"code": " spring20 "}
    )
    assert checked.status_code == 200, checked.text
    quote = checked.json()
    assert (quote["subtotal"], quote["discount"], quote["promo_code"]) == (
        100_000,
        15_000,
        "SPRING20",
    )

    created = await book(client, headers, held["hold_id"], promo_code="spring20")
    assert created.status_code == 201, created.text
    booking = created.json()
    assert (booking["discount"], booking["total_due"]) == (15_000, 85_000)

    listed = (await owner_client.get(f"{ADMIN}/promo-codes")).json()
    assert listed[0]["uses"] == 1

    # one use per client
    second = (await hold(client, headers, local(MONDAY, 15), [world.haircut], world.first)).json()
    used = await client.post(
        f"{MINI}/holds/{second['hold_id']}/promo", headers=headers, json={"code": "SPRING20"}
    )
    assert used.json()["error"]["code"] == "promo_already_used"
    rejected = await book(client, headers, second["hold_id"], promo_code="SPRING20")
    assert rejected.status_code == 422

    # cancelling gives the use back
    cancel = await client.post(f"{MINI}/bookings/{booking['id']}/cancel", headers=headers, json={})
    assert cancel.status_code == 200
    again = await client.post(
        f"{MINI}/holds/{second['hold_id']}/promo", headers=headers, json={"code": "SPRING20"}
    )
    assert again.status_code == 200

    stored = (
        await session.execute(select(Booking).where(Booking.id == booking["id"]))
    ).scalar_one()
    assert stored.promo_code_id is not None
    assert str(stored.promo_code_id) == promo["id"]


@pytest.mark.usefixtures("clock")
async def test_promo_rules(
    client: httpx.AsyncClient,
    owner_client: httpx.AsyncClient,
    session: AsyncSession,
    world: World,  # noqa: F811
) -> None:
    await _create(owner_client, code="BIG", kind="fixed", value=10_000, min_subtotal=150_000)
    await _create(owner_client, code="OLD", valid_to=(MONDAY - timedelta(days=1)).isoformat())
    await _create(owner_client, code="SOON", valid_from=(MONDAY + timedelta(days=1)).isoformat())
    await _create(owner_client, code="FIRST", first_visit_only=True)
    await _create(owner_client, code="ONCE", max_uses=1)
    off = await _create(owner_client, code="OFF")
    await owner_client.patch(f"{ADMIN}/promo-codes/{off['id']}", json={"is_active": False})

    headers = await register(client, 9200)
    held = (await hold(client, headers, local(MONDAY, 12), [world.haircut], world.first)).json()

    async def code_of(code: str) -> str | None:
        response = await client.post(
            f"{MINI}/holds/{held['hold_id']}/promo", headers=headers, json={"code": code}
        )
        return None if response.status_code == 200 else response.json()["error"]["code"]

    assert await code_of("BIG") == "promo_min_subtotal"
    assert await code_of("OLD") == "promo_expired"
    assert await code_of("SOON") == "promo_not_started"
    assert await code_of("OFF") == "promo_not_found"
    assert await code_of("FIRST") is None

    created = await book(client, headers, held["hold_id"], promo_code="ONCE")
    assert created.status_code == 201
    other = await register(client, 9201)
    held2 = (await hold(client, other, local(MONDAY, 15), [world.haircut], world.first)).json()
    response = await client.post(
        f"{MINI}/holds/{held2['hold_id']}/promo", headers=other, json={"code": "ONCE"}
    )
    assert response.json()["error"]["code"] == "promo_used_up"

    # a client with a completed visit is not a first-timer
    booking = (
        await session.execute(select(Booking).where(Booking.id == created.json()["id"]))
    ).scalar_one()
    booking.status = BookingStatus.COMPLETED
    await session.commit()
    held3 = (await hold(client, headers, local(MONDAY, 17), [world.haircut], world.first)).json()
    first = await client.post(
        f"{MINI}/holds/{held3['hold_id']}/promo", headers=headers, json={"code": "FIRST"}
    )
    assert first.json()["error"]["code"] == "promo_first_visit"
