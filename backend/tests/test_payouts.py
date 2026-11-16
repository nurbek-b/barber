"""Barber payouts: earned share of completed visits minus payouts; owner-only writes."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Barber, Booking, BookingService, Branch, Client, TelegramOutbox
from app.models.enums import AdminRole, BookingStatus
from tests.conftest import AdminFactory, login_as

ADMIN = "/api/v1/admin"


async def _visit(
    session: AsyncSession,
    branch: Branch,
    barber: Barber,
    subtotal: int,
    days_ago: int,
    bp: int | None,
) -> None:
    client = Client(
        branch_id=branch.id,
        name="К",
        phone=f"+99670{days_ago:07d}",
        referral_code=f"R{days_ago}x{subtotal}",
    )
    session.add(client)
    await session.flush()
    end = datetime.now(UTC) - timedelta(days=days_ago)
    session.add(
        Booking(
            branch_id=branch.id,
            client_id=client.id,
            barber_id=barber.id,
            status=BookingStatus.COMPLETED,
            start_at=end - timedelta(hours=1),
            end_at=end,
            blocked_until=end,
            subtotal=subtotal,
            bonus_spent=0,
            total_due=subtotal,
            paid_amount=subtotal,
            completed_at=end,
            barber_commission_bp=bp,
            services=[
                BookingService(name_snapshot={"ru": "Стрижка"}, duration_min=60, price=subtotal)
            ],
        )
    )
    await session.commit()


async def test_payout_balances(
    client: httpx.AsyncClient,
    make_admin: AdminFactory,
    session: AsyncSession,
    branch: Branch,
) -> None:
    barber = Barber(branch_id=branch.id, name="Канат", commission_bp=4000, telegram_chat_id=555)
    session.add(barber)
    await session.commit()
    await _visit(session, branch, barber, 100_000, 3, 5000)  # rate at completion: 50%
    await _visit(session, branch, barber, 80_000, 2, None)  # no stored rate: today's 40%
    today = date.today().isoformat()

    await login_as(client, await make_admin(AdminRole.ADMIN))
    rows = (await client.get(f"{ADMIN}/payouts/balances", params={"until": today})).json()
    row = next(r for r in rows if r["barber_id"] == str(barber.id))
    assert (row["earned"], row["paid"], row["due"]) == (82_000, 0, 82_000)
    forbidden = await client.post(
        f"{ADMIN}/payouts", json={"barber_id": str(barber.id), "amount": 1, "paid_on": today}
    )
    assert forbidden.status_code == 403, "only the owner pays"

    await login_as(client, await make_admin(AdminRole.OWNER))
    created = await client.post(
        f"{ADMIN}/payouts",
        json={"barber_id": str(barber.id), "amount": 50_000, "paid_on": today, "note": "аванс"},
    )
    assert created.status_code == 201, created.text
    row = next(
        r
        for r in (await client.get(f"{ADMIN}/payouts/balances", params={"until": today})).json()
        if r["barber_id"] == str(barber.id)
    )
    assert (row["paid"], row["due"], row["last_paid_on"]) == (50_000, 32_000, today)
    sent = await session.scalar(
        select(TelegramOutbox).where(TelegramOutbox.template_key == "payout_barber")
    )
    assert sent is not None
    assert sent.chat_id == 555

    history = (await client.get(f"{ADMIN}/payouts")).json()
    assert [(p["amount"], p["note"]) for p in history] == [(50_000, "аванс")]
    assert (await client.delete(f"{ADMIN}/payouts/{history[0]['id']}")).status_code == 204
    assert (await client.get(f"{ADMIN}/payouts")).json() == []
