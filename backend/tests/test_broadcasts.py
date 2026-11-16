"""Broadcasts: segments, exclusions (unsubscribed / blocked), promo attached, outbox only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Barber, Booking, Branch, Client, TelegramOutbox, User
from app.models.enums import AdminRole, BookingStatus
from app.notify.templates import render
from tests.conftest import AdminFactory, login_as

ADMIN = "/api/v1/admin"


async def _people(session: AsyncSession, branch: Branch) -> dict[str, Client]:
    now = datetime.now(UTC)
    barber = Barber(branch_id=branch.id, name="Мастер")
    session.add(barber)
    await session.flush()
    people: dict[str, Client] = {}

    async def person(key: str, tg: int | None, **fields: Any) -> Client:
        user = None
        if tg is not None:
            user = User(
                telegram_id=tg, first_name=key, bot_blocked=fields.pop("bot_blocked", False)
            )
            session.add(user)
            await session.flush()
        client = Client(
            branch_id=branch.id,
            user_id=user.id if user else None,
            name=key,
            referral_code=f"ref{key}",
            **fields,
        )
        session.add(client)
        await session.flush()
        people[key] = client
        return client

    def visit(client: Client, days: int, status: BookingStatus = BookingStatus.COMPLETED) -> None:
        start = now + timedelta(days=days)
        session.add(
            Booking(
                branch_id=branch.id,
                client_id=client.id,
                barber_id=barber.id,
                status=status,
                start_at=start,
                end_at=start + timedelta(hours=1),
                blocked_until=start + timedelta(hours=1),
                subtotal=1,
                bonus_spent=0,
                total_due=1,
            )
        )

    lapsed = await person("lapsed", 1, tags=["vip"], birthday=now.date().replace(year=1990))
    visit(lapsed, -90)
    await person("newbie", 2)
    unsub = await person("unsub", 3, marketing_opt_out=True)
    visit(unsub, -90)
    await person("phone_only", None)
    blocked_bot = await person("blocked_bot", 4, bot_blocked=True)
    visit(blocked_bot, -90)
    returning = await person("returning", 5)
    visit(returning, -90)
    visit(returning, 3, BookingStatus.CONFIRMED)  # already booked again
    await session.commit()
    return people


async def test_segments_and_send(
    owner_client: httpx.AsyncClient, session: AsyncSession, branch: Branch
) -> None:
    await _people(session, branch)

    async def count(**segment: Any) -> int:
        response = await owner_client.post(f"{ADMIN}/broadcasts/preview", json=segment)
        assert response.status_code == 200, response.text
        return int(response.json()["recipients"])

    assert await count(kind="all") == 3  # lapsed, newbie, returning
    assert await count(kind="inactive", days=60) == 1  # returning has a booking ahead
    assert await count(kind="never_visited") == 1
    assert await count(kind="tag", tag="vip") == 1
    assert await count(kind="birthday_month") == 1
    bad = await owner_client.post(f"{ADMIN}/broadcasts/preview", json={"kind": "inactive"})
    assert bad.status_code == 422

    promo = await owner_client.post(
        f"{ADMIN}/promo-codes", json={"code": "COMEBACK", "kind": "percent", "value": 1500}
    )
    sent = await owner_client.post(
        f"{ADMIN}/broadcasts",
        json={
            "segment": {"kind": "inactive", "days": 60},
            "texts": {"ru": "Давно не виделись! Скидка 15%", "ky": "", "en": "We miss you"},
            "promo_code_id": promo.json()["id"],
        },
    )
    assert sent.status_code == 201, sent.text
    assert sent.json()["recipients"] == 1
    assert sent.json()["promo_code"] == "COMEBACK"

    rows = (
        (
            await session.execute(
                select(TelegramOutbox).where(TelegramOutbox.template_key == "broadcast")
            )
        )
        .scalars()
        .all()
    )
    assert [row.chat_id for row in rows] == [1]
    text = render("broadcast", rows[0].language, rows[0].payload, None)
    assert text == "Давно не виделись! Скидка 15%\n\n🎁 COMEBACK"
    buttons = rows[0].payload["buttons"]
    assert buttons[-1] == [{"text": "Отписаться", "callback_data": "unsub"}]

    history = (await owner_client.get(f"{ADMIN}/broadcasts")).json()
    assert history[0]["recipients"] == 1

    no_ru = await owner_client.post(
        f"{ADMIN}/broadcasts", json={"segment": {"kind": "all"}, "texts": {"en": "Hi"}}
    )
    assert no_ru.json()["error"]["code"] == "text_required"


async def test_barbers_cannot_broadcast(
    client: httpx.AsyncClient, make_admin: AdminFactory
) -> None:
    await login_as(client, await make_admin(AdminRole.BARBER))
    response = await client.post(f"{ADMIN}/broadcasts/preview", json={"kind": "all"})
    assert response.status_code == 403
