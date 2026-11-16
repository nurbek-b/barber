"""QR payments: prepayment for unreliable clients, "I paid" claims, salon confirmation."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Booking, Client, TelegramOutbox
from app.models.enums import BookingStatus
from app.services.payments import prepay_amount
from app.worker.prepay import cancel_unpaid
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
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def test_prepay_rounds_up_to_whole_som() -> None:
    class Salon:
        prepay_percent = 30

    assert prepay_amount(Salon(), 100_000) == 30_000  # type: ignore[arg-type]
    assert prepay_amount(Salon(), 85_050) == 25_600  # 255.15 → 256 som
    assert prepay_amount(Salon(), 0) == 0  # type: ignore[arg-type]


async def _templates(session: AsyncSession, booking_id: str) -> list[str]:
    rows = await session.scalars(
        select(TelegramOutbox.template_key)
        .where(TelegramOutbox.booking_id == booking_id)
        .order_by(TelegramOutbox.id)
    )
    return list(rows)


async def _enable_prepay(owner: httpx.AsyncClient, **extra: object) -> None:
    current = (await owner.get(f"{ADMIN}/settings/salon")).json()
    body = {**current, "prepay_percent": 50, "prepay_after_no_shows": 1, **extra}
    saved = await owner.put(f"{ADMIN}/settings/salon", json=body)
    assert saved.status_code == 200, saved.text


@pytest.mark.usefixtures("clock")
async def test_prepayment_flow(
    client: httpx.AsyncClient,
    owner_client: httpx.AsyncClient,
    session: AsyncSession,
    world: World,  # noqa: F811
) -> None:
    await _enable_prepay(owner_client, payment_note="MBank, Канат")
    headers = await register(client, 9200)
    me = await session.scalar(select(Client).where(Client.phone.like("%9200")))
    assert me is not None

    # a reliable client books as usual
    held = (await hold(client, headers, local(MONDAY, 12), [world.haircut], world.first)).json()
    assert held["quote"]["prepay_percent"] == 0
    normal = (await book(client, headers, held["hold_id"])).json()
    assert (normal["status"], normal["prepay_due"]) == ("confirmed", 0)

    # after a no-show the next booking waits for 50%
    me.no_show_count = 1
    await session.commit()
    held = (await hold(client, headers, local(MONDAY, 15), [world.haircut], world.first)).json()
    assert held["quote"]["prepay_percent"] == 50
    created = await book(client, headers, held["hold_id"])
    booking = created.json()
    assert (booking["status"], booking["prepay_due"], booking["payment_status"]) == (
        "pending",
        50_000,
        "unpaid",
    )
    assert booking["can_pay"] is False, "no QR uploaded yet"
    templates = await _templates(session, booking["id"])
    assert "booking_prepay_client" in templates
    assert "booking_created_client" not in templates
    assert "booking_created_admin" in templates

    pay_url = f"{MINI}/bookings/{booking['id']}/payment"
    no_qr = await client.post(pay_url, headers=headers, json={"amount": 50_000})
    assert no_qr.json()["error"]["code"] == "no_payment_qr"

    # the owner uploads the salon QR; the barber's own QR wins over it
    salon = await owner_client.post(
        f"{ADMIN}/settings/salon/payment-qr", files={"file": ("qr.png", PNG, "image/png")}
    )
    assert salon.status_code == 200, salon.text
    salon_qr = salon.json()["payment_qr_url"]
    info = (await client.get(pay_url, headers=headers)).json()
    assert (info["qr_url"], info["note"], info["amount_left"]) == (salon_qr, "MBank, Канат", 50_000)
    barber = await owner_client.post(
        f"{ADMIN}/barbers/{world.first.id}/payment-qr",
        files={"file": ("qr.png", PNG, "image/png")},
    )
    assert barber.status_code == 200, barber.text
    info = (await client.get(pay_url, headers=headers)).json()
    assert info["qr_url"] == barber.json()["payment_qr_url"] != salon_qr

    too_much = await client.post(pay_url, headers=headers, json={"amount": 100_001})
    assert too_much.json()["error"]["code"] == "bad_amount"
    claimed = await client.post(pay_url, headers=headers, json={"amount": 50_000})
    assert claimed.status_code == 200, claimed.text
    assert (claimed.json()["claimed"], claimed.json()["payment_status"]) == (True, "claimed")
    assert "payment_claimed_admin" in await _templates(session, booking["id"])

    payments = (await owner_client.get(f"{ADMIN}/bookings/{booking['id']}/payments")).json()
    assert [(p["status"], p["amount"], p["by_client"]) for p in payments] == [
        ("claimed", 50_000, True)
    ]
    # the bank shows 40 000 only: confirm what arrived — not enough to confirm the booking
    decided = await owner_client.post(
        f"{ADMIN}/payments/{payments[0]['id']}/confirm", json={"amount": 40_000}
    )
    assert decided.status_code == 200, decided.text
    again = await owner_client.post(f"{ADMIN}/payments/{payments[0]['id']}/confirm", json={})
    assert again.status_code == 409
    view = (await client.get(f"{MINI}/bookings/{booking['id']}", headers=headers)).json()
    assert (view["status"], view["prepaid_amount"], view["payment_status"]) == (
        "pending",
        40_000,
        "partial",
    )
    assert "payment_confirmed_client" in await _templates(session, booking["id"])

    # a second claim is rejected, a deposit added by the admin covers the prepayment
    second = await client.post(pay_url, headers=headers, json={"amount": 10_000})
    second_id = (await owner_client.get(f"{ADMIN}/bookings/{booking['id']}/payments")).json()[0][
        "id"
    ]
    assert second.status_code == 200
    rejected = await owner_client.post(f"{ADMIN}/payments/{second_id}/reject")
    assert rejected.json()["status"] == "rejected"
    assert "payment_rejected_client" in await _templates(session, booking["id"])
    added = await owner_client.post(
        f"{ADMIN}/bookings/{booking['id']}/payments", json={"amount": 60_000, "method": "cash"}
    )
    assert added.status_code == 201, added.text
    view = (await client.get(f"{MINI}/bookings/{booking['id']}", headers=headers)).json()
    assert (view["status"], view["prepaid_amount"], view["payment_status"]) == (
        "confirmed",
        100_000,
        "paid",
    )
    assert view["can_pay"] is False
    assert "payment_confirmed_booking_client" in await _templates(session, booking["id"])
    admin_view = (await owner_client.get(f"{ADMIN}/bookings/{booking['id']}")).json()
    assert admin_view["payment_status"] == "paid"


@pytest.mark.usefixtures("clock")
async def test_flagged_client_and_unpaid_timeout(
    client: httpx.AsyncClient,
    owner_client: httpx.AsyncClient,
    session: AsyncSession,
    maker: async_sessionmaker[AsyncSession],
    world: World,  # noqa: F811
) -> None:
    await _enable_prepay(owner_client, prepay_after_no_shows=5, prepay_timeout_min=60)
    headers = await register(client, 9201)
    me = await session.scalar(select(Client).where(Client.phone.like("%9201")))
    assert me is not None
    flagged = await owner_client.patch(f"{ADMIN}/clients/{me.id}", json={"prepay_required": True})
    assert flagged.json()["prepay_required"] is True

    held = (await hold(client, headers, local(MONDAY, 12), [world.haircut], world.first)).json()
    booking = (await book(client, headers, held["hold_id"])).json()
    assert booking["status"] == "pending"

    stored = await session.get(Booking, booking["id"])
    assert stored is not None
    created_at = stored.created_at
    assert await cancel_unpaid(maker, None, created_at + timedelta(minutes=59)) == 0
    assert await cancel_unpaid(maker, None, created_at + timedelta(minutes=61)) == 1
    await session.refresh(stored)
    assert stored.status is BookingStatus.CANCELLED
    assert stored.cancel_reason == "prepayment not received"
    assert "booking_cancelled_client" in await _templates(session, booking["id"])
