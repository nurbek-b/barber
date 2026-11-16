"""Shop: products, orders paid by QR with "I paid" claims, statuses and stock."""

from __future__ import annotations

import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product, SalonSettings, TelegramOutbox
from tests.test_bookings_miniapp import MINI, register

ADMIN = "/api/v1/admin"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


async def _templates(session: AsyncSession) -> list[str]:
    return list(await session.scalars(select(TelegramOutbox.template_key)))


async def _order(http: httpx.AsyncClient, headers: dict[str, str], items: list[dict[str, object]]):  # type: ignore[no-untyped-def]
    return await http.post(
        f"{MINI}/orders",
        headers={**headers, "Idempotency-Key": uuid.uuid4().hex},
        json={"items": items},
    )


async def test_shop_flow(
    client: httpx.AsyncClient, owner_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    wax = await owner_client.post(
        f"{ADMIN}/products",
        json={"name_i18n": {"ru": "Воск"}, "price": 90_000, "stock": 3},
    )
    assert wax.status_code == 201, wax.text
    oil = await owner_client.post(
        f"{ADMIN}/products", json={"name_i18n": {"ru": "Масло"}, "price": 50_000}
    )
    hidden = await owner_client.post(
        f"{ADMIN}/products", json={"name_i18n": {"ru": "Старое"}, "price": 1, "is_active": False}
    )
    photo = await owner_client.post(
        f"{ADMIN}/products/{wax.json()['id']}/photo", files={"file": ("w.png", PNG, "image/png")}
    )
    assert photo.json()["photo_url"]

    headers = await register(client, 9400)
    salon = await session.scalar(select(SalonSettings))
    assert salon is not None
    salon.admin_chat_id = -100555
    await session.commit()
    shown = (await client.get(f"{MINI}/products", headers=headers)).json()
    assert {p["name_i18n"]["ru"] for p in shown} == {"Воск", "Масло"}

    unavailable = await _order(
        client, headers, [{"product_id": hidden.json()["id"], "quantity": 1}]
    )
    assert unavailable.json()["error"]["code"] == "product_unavailable"
    too_many = await _order(client, headers, [{"product_id": wax.json()["id"], "quantity": 4}])
    assert too_many.json()["error"]["code"] == "out_of_stock"

    placed = await _order(
        client,
        headers,
        [
            {"product_id": wax.json()["id"], "quantity": 2},
            {"product_id": oil.json()["id"], "quantity": 1},
        ],
    )
    assert placed.status_code == 201, placed.text
    order = placed.json()
    assert (order["status"], order["total"], order["number"]) == ("new", 230_000, 1)
    assert (await session.get(Product, uuid.UUID(wax.json()["id"]))).stock == 1  # type: ignore[union-attr]
    assert "order_created_admin" in await _templates(session)

    pay_url = f"{MINI}/orders/{order['id']}/payment"
    no_qr = await client.post(pay_url, headers=headers)
    assert no_qr.json()["error"]["code"] == "no_payment_qr"
    await session.refresh(salon)
    salon.payment_qr_url = "/media/salon/qr.png"
    await session.commit()

    info = (await client.get(pay_url, headers=headers)).json()
    assert (info["qr_url"], info["amount_left"]) == ("/media/salon/qr.png", 230_000)
    claimed = await client.post(pay_url, headers=headers)
    assert claimed.json()["status"] == "payment_claimed"
    assert "order_paid_claimed_admin" in await _templates(session)

    # the money did not arrive → back to "new"; the client claims again; the salon confirms
    rows = (await owner_client.get(f"{ADMIN}/orders", params={"status": "payment_claimed"})).json()
    assert [r["id"] for r in rows] == [order["id"]]
    rejected = await owner_client.post(f"{ADMIN}/orders/{order['id']}/reject-payment")
    assert rejected.json()["status"] == "new"
    await client.post(pay_url, headers=headers)
    current = (await owner_client.get(f"{ADMIN}/orders")).json()[0]
    for step in ("paid", "ready", "completed"):
        changed = await owner_client.post(
            f"{ADMIN}/orders/{order['id']}/status",
            json={"version": current["version"], "status": step},
        )
        assert changed.status_code == 200, changed.text
        current = changed.json()
    assert (current["status"], current["paid_amount"]) == ("completed", 230_000)
    sent = await _templates(session)
    for template in ("order_payment_rejected_client", "order_paid_client", "order_ready_client"):
        assert template in sent
    stale = await owner_client.post(
        f"{ADMIN}/orders/{order['id']}/status", json={"version": 1, "status": "cancelled"}
    )
    assert stale.status_code == 409

    # a client cancels an unpaid order: the stock comes back
    second = (
        await _order(client, headers, [{"product_id": wax.json()["id"], "quantity": 1}])
    ).json()
    assert (await session.get(Product, uuid.UUID(wax.json()["id"]))).stock == 0  # type: ignore[union-attr]
    cancelled = await client.post(f"{MINI}/orders/{second['id']}/cancel", headers=headers)
    assert cancelled.json()["status"] == "cancelled"
    product = await session.get(Product, uuid.UUID(wax.json()["id"]))
    assert product is not None
    await session.refresh(product)
    assert product.stock == 1
    mine = (await client.get(f"{MINI}/orders", headers=headers)).json()
    assert [o["status"] for o in mine] == ["cancelled", "completed"]
