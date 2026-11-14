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
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_now
from app.core.security.initdata import build_init_data
from app.models import (
    AuditLog,
    Barber,
    BarberSchedule,
    BarberService,
    BonusSettings,
    BonusTransaction,
    Booking,
    Branch,
    Client,
    LoyaltyLevel,
    Service,
    TelegramOutbox,
)
from app.models.enums import AdminRole, BonusTxType
from app.services.bonus import BonusService
from app.services.bonus_ledger import BonusLedger, NotEnoughBonusesError
from tests.conftest import BOT_TOKEN, AdminFactory, login_as, tma_header

TZ = ZoneInfo("Asia/Bishkek")
MONDAY = date(2026, 12, 7)
NOW = datetime.combine(MONDAY, time(8), tzinfo=TZ).astimezone(UTC)
MINI = "/api/v1/miniapp"
ADMIN = "/api/v1/admin"


def local(day: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=TZ).astimezone(UTC)


@pytest.fixture
def clock(app: FastAPI) -> Iterator[list[datetime]]:
    current = [NOW]
    app.dependency_overrides[get_now] = lambda: current[0]
    yield current
    app.dependency_overrides.pop(get_now, None)


@pytest.fixture
async def bonus_on(session: AsyncSession, branch: Branch) -> BonusSettings:
    settings = await session.get(BonusSettings, branch.id)
    assert settings is not None
    settings.enabled = True
    settings.base_cashback_bp = 500
    settings.max_spend_bp = 3000
    settings.lifetime_days = 180
    await session.commit()
    return settings


async def make_client(session: AsyncSession, branch: Branch, name: str = "Клиент") -> Client:
    client = Client(branch_id=branch.id, name=name, referral_code=uuid.uuid4().hex[:8])
    session.add(client)
    await session.commit()
    return client


# ---------------------------------------------------------------------------
# ledger
# ---------------------------------------------------------------------------


async def test_ledger_credit_debit_fifo(
    session: AsyncSession, branch: Branch, bonus_on: BonusSettings
) -> None:
    ledger = BonusLedger(session)
    client = await make_client(session, branch)
    locked = await ledger.lock_client(client.id)
    late = await ledger.credit(
        locked, BonusTxType.MANUAL, 1000, NOW, comment="a", expires_at=NOW + timedelta(days=90)
    )
    soon = await ledger.credit(
        locked, BonusTxType.MANUAL, 300, NOW, comment="b", expires_at=NOW + timedelta(days=10)
    )
    assert late is not None
    assert soon is not None
    debit = await ledger.debit(locked, BonusTxType.SPEND, 500, NOW)
    await session.commit()

    assert debit.amount == -500
    assert debit.balance_after == 800
    lots = {lot.tx_id: lot.remaining for lot in await ledger.lots(client.id)}
    assert lots == {late.id: 800}, "the soon-expiring lot is fully used first"
    assert await ledger.ledger_sum(client.id) == 800
    refreshed = await session.get(Client, client.id)
    assert refreshed is not None
    assert refreshed.bonus_balance == 800

    with pytest.raises(NotEnoughBonusesError):
        await ledger.debit(await ledger.lock_client(client.id), BonusTxType.SPEND, 801, NOW)
    await session.rollback()


async def test_dedupe_key_makes_credit_idempotent(
    session: AsyncSession, branch: Branch, bonus_on: BonusSettings
) -> None:
    ledger = BonusLedger(session)
    client = await ledger.lock_client((await make_client(session, branch)).id)
    first = await ledger.credit(client, BonusTxType.WELCOME, 100, NOW, dedupe_key="welcome:x")
    second = await ledger.credit(client, BonusTxType.WELCOME, 100, NOW, dedupe_key="welcome:x")
    assert first is not None
    assert second is None
    assert client.bonus_balance == 100


async def test_concurrent_spends_never_overdraw(
    maker: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    branch: Branch,
    bonus_on: BonusSettings,
) -> None:
    client = await make_client(session, branch)
    ledger = BonusLedger(session)
    await ledger.credit(
        await ledger.lock_client(client.id), BonusTxType.MANUAL, 1000, NOW, comment="seed"
    )
    await session.commit()

    async def spend() -> bool:
        async with maker() as other:
            other_ledger = BonusLedger(other)
            try:
                locked = await other_ledger.lock_client(client.id)
                await asyncio.sleep(0.01)  # widen the race window
                await other_ledger.debit(locked, BonusTxType.SPEND, 300, NOW)
                await other.commit()
                return True
            except NotEnoughBonusesError:
                await other.rollback()
                return False

    results = await asyncio.gather(*(spend() for _ in range(5)))
    assert sorted(results) == [False, False, True, True, True]
    assert await BonusLedger(session).ledger_sum(client.id) == 100
    refreshed = await session.scalar(select(Client.bonus_balance).where(Client.id == client.id))
    assert refreshed == 100


async def test_refund_restores_original_expiry_with_floor(
    session: AsyncSession, branch: Branch, bonus_on: BonusSettings
) -> None:
    ledger = BonusLedger(session)
    client = await ledger.lock_client((await make_client(session, branch)).id)
    await ledger.credit(
        client, BonusTxType.MANUAL, 100, NOW, comment="a", expires_at=NOW + timedelta(days=2)
    )
    await ledger.credit(
        client, BonusTxType.MANUAL, 100, NOW, comment="b", expires_at=NOW + timedelta(days=60)
    )
    booking_id = uuid.uuid4()
    session.add(
        Booking(
            id=booking_id,
            branch_id=branch.id,
            client_id=client.id,
            barber_id=(await _barber(session, branch)).id,
            start_at=NOW,
            end_at=NOW + timedelta(hours=1),
            blocked_until=NOW + timedelta(hours=1),
            subtotal=200,
            bonus_spent=150,
            total_due=50,
        )
    )
    await session.flush()
    await ledger.debit(client, BonusTxType.SPEND, 150, NOW, booking_id=booking_id)

    later = NOW + timedelta(days=1)
    assert await ledger.refund_booking(client, booking_id, later, amount=40) == 40
    assert await ledger.refund_booking(client, booking_id, later) == 110
    assert await ledger.refund_booking(client, booking_id, later) == 0, "nothing left"
    refunds = (
        await session.execute(
            select(BonusTransaction.amount, BonusTransaction.expires_at)
            .where(BonusTransaction.type == BonusTxType.REFUND)
            .order_by(BonusTransaction.created_at, BonusTransaction.amount)
        )
    ).all()
    assert sum(amount for amount, _ in refunds) == 150
    expiries = [expires for _, expires in refunds if expires is not None]
    # 50 of the 60-day lot and 100 of the 2-day lot were spent; the 2-day lot gets the
    # 7-day floor from the refund moment
    assert max(expiries) == NOW + timedelta(days=60)
    assert min(expiries) == later + timedelta(days=7)
    assert client.bonus_balance == 200


async def _barber(session: AsyncSession, branch: Branch) -> Barber:
    barber = Barber(branch_id=branch.id, name="M")
    session.add(barber)
    await session.flush()
    return barber


async def test_expire_due_burns_only_remaining(
    session: AsyncSession, branch: Branch, bonus_on: BonusSettings
) -> None:
    ledger = BonusLedger(session)
    client = await ledger.lock_client((await make_client(session, branch)).id)
    await ledger.credit(
        client, BonusTxType.MANUAL, 500, NOW, comment="old", expires_at=NOW + timedelta(days=1)
    )
    await ledger.credit(
        client, BonusTxType.MANUAL, 200, NOW, comment="new", expires_at=NOW + timedelta(days=30)
    )
    await ledger.debit(client, BonusTxType.SPEND, 300, NOW)  # takes 300 of the old lot
    await session.commit()

    service = BonusService(session)
    assert await service.expire_due(NOW + timedelta(days=2)) == 200
    await session.commit()
    assert await service.expire_due(NOW + timedelta(days=2)) == 0, "idempotent"
    await session.commit()
    balance = await session.scalar(select(Client.bonus_balance).where(Client.id == client.id))
    assert balance == 200
    assert await BonusLedger(session).ledger_sum(client.id) == 200


# ---------------------------------------------------------------------------
# admin API
# ---------------------------------------------------------------------------


async def test_settings_permissions(
    client: httpx.AsyncClient, make_admin: AdminFactory, app: FastAPI
) -> None:
    await login_as(client, await make_admin(AdminRole.ADMIN))
    assert (await client.get(f"{ADMIN}/settings/bonus")).status_code == 200
    body = (await client.get(f"{ADMIN}/settings/bonus")).json()
    assert (await client.put(f"{ADMIN}/settings/bonus", json=body)).status_code == 403
    assert (await client.get(f"{ADMIN}/loyalty-levels")).status_code == 200

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as owner:
        await login_as(owner, await make_admin(AdminRole.OWNER))
        body.update(enabled=True, welcome_enabled=True, welcome_amount=0)
        assert (await owner.put(f"{ADMIN}/settings/bonus", json=body)).status_code == 422
        body["welcome_amount"] = 20_000
        updated = await owner.put(f"{ADMIN}/settings/bonus", json=body)
        assert updated.status_code == 200
        assert updated.json()["welcome_amount"] == 20_000

        level = await owner.post(
            f"{ADMIN}/loyalty-levels",
            json={
                "name_i18n": {"ru": "Платина"},
                "min_visits": 50,
                "min_spent": 10_000_000,
                "cashback_bp": 1000,
                "sort_order": 3,
                "color": "#e5e4e2",
            },
        )
        assert level.status_code == 201
        assert len((await owner.get(f"{ADMIN}/loyalty-levels")).json()) == 4
        bad = await owner.post(
            f"{ADMIN}/loyalty-levels", json={"name_i18n": {"ru": "X"}, "cashback_bp": 20_000}
        )
        assert bad.status_code == 422
        assert (
            await owner.delete(f"{ADMIN}/loyalty-levels/{level.json()['id']}")
        ).status_code == 204


async def test_manual_adjust(
    owner_client: httpx.AsyncClient,
    session: AsyncSession,
    branch: Branch,
    bonus_on: BonusSettings,
    clock: list[datetime],
) -> None:
    client = await make_client(session, branch)
    url = f"{ADMIN}/clients/{client.id}/bonus/adjust"
    no_comment = await owner_client.post(url, json={"amount": 100, "comment": "   "})
    assert no_comment.status_code == 422
    zero = await owner_client.post(url, json={"amount": 0, "comment": "ноль"})
    assert zero.status_code == 422

    credit = await owner_client.post(
        url, json={"amount": 50_000, "comment": "компенсация", "expires_in_days": 30}
    )
    assert credit.status_code == 201, credit.text
    assert credit.json()["balance_after"] == 50_000
    assert credit.json()["expires_at"].startswith("2027-01-06")

    over = await owner_client.post(url, json={"amount": -60_000, "comment": "ошибка"})
    assert over.status_code == 422
    assert over.json()["error"]["code"] == "not_enough_bonuses"
    debit = await owner_client.post(url, json={"amount": -20_000, "comment": "ошибка"})
    assert debit.json()["balance_after"] == 30_000

    card = (await owner_client.get(f"{ADMIN}/clients/{client.id}/bonus")).json()
    assert card["balance"] == card["ledger_balance"] == 30_000
    assert [tx["type"] for tx in card["transactions"]] == ["manual", "manual"]
    audits = await session.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "bonus.adjust")
    )
    assert audits == 2


async def test_barber_cannot_adjust(
    client: httpx.AsyncClient, make_admin: AdminFactory, session: AsyncSession, branch: Branch
) -> None:
    target = await make_client(session, branch)
    await login_as(client, await make_admin(AdminRole.BARBER))
    response = await client.post(
        f"{ADMIN}/clients/{target.id}/bonus/adjust", json={"amount": 100, "comment": "хочу"}
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# end-to-end: welcome → spend → cancel/refund → complete/earn → level → referral
# ---------------------------------------------------------------------------


class World:
    barber: Barber
    haircut: Service


@pytest.fixture
async def world(session: AsyncSession, branch: Branch, bonus_on: BonusSettings) -> World:
    w = World()
    w.haircut = Service(
        branch_id=branch.id, name_i18n={"ru": "Стрижка"}, duration_min=60, base_price=100_000
    )
    w.barber = Barber(branch_id=branch.id, name="Мастер")
    session.add_all([w.haircut, w.barber])
    await session.flush()
    session.add(BarberService(barber_id=w.barber.id, service_id=w.haircut.id))
    session.add_all(
        BarberSchedule(barber_id=w.barber.id, weekday=d, start_time=time(10), end_time=time(19))
        for d in range(7)
    )
    bonus_on.welcome_enabled = True
    bonus_on.welcome_amount = 50_000
    bonus_on.referral_enabled = True
    bonus_on.referrer_amount = 30_000
    bonus_on.referee_amount = 10_000
    await session.commit()
    return w


async def register(
    http: httpx.AsyncClient, telegram_id: int, start_param: str | None = None
) -> dict[str, str]:
    headers = tma_header(telegram_id, start_param=start_param)
    contact = build_init_data(
        {
            "contact": json.dumps(
                {"user_id": telegram_id, "phone_number": f"9967{telegram_id:08d}"}
            ),
            "auth_date": str(int(datetime.now(UTC).timestamp())),
        },
        BOT_TOKEN,
    )
    assert (
        await http.post(f"{MINI}/me/phone", headers=headers, json={"contact": contact})
    ).status_code == 200
    return headers


async def book(
    http: httpx.AsyncClient, headers: dict[str, str], world: World, start: datetime, bonus: int = 0
) -> httpx.Response:
    held = await http.post(
        f"{MINI}/holds",
        headers=headers,
        json={
            "barber_id": str(world.barber.id),
            "service_ids": [str(world.haircut.id)],
            "start_at": start.isoformat(),
        },
    )
    assert held.status_code == 201, held.text
    return await http.post(
        f"{MINI}/bookings",
        headers={**headers, "Idempotency-Key": uuid.uuid4().hex},
        json={"hold_id": held.json()["hold_id"], "bonus_to_spend": bonus},
    )


async def complete(
    owner: httpx.AsyncClient, booking: dict[str, Any], paid: int | None = None
) -> httpx.Response:
    detail = (await owner.get(f"{ADMIN}/bookings/{booking['id']}")).json()
    body: dict[str, Any] = {
        "version": detail["version"],
        "status": "completed",
        "payment_method": "cash",
    }
    if paid is not None:
        body["paid_amount"] = paid
    return await owner.post(f"{ADMIN}/bookings/{booking['id']}/status", json=body)


async def test_full_loyalty_flow(
    client: httpx.AsyncClient,
    owner_client: httpx.AsyncClient,
    world: World,
    session: AsyncSession,
    clock: list[datetime],
) -> None:
    alice = await register(client, 1001)
    assert (await client.get(f"{MINI}/me", headers=alice)).json()["bonus_balance"] == 50_000

    # hold quote shows the limit: min(balance 50k, 30% of 100k) = 30k
    held = await client.post(
        f"{MINI}/holds",
        headers=alice,
        json={
            "barber_id": str(world.barber.id),
            "service_ids": [str(world.haircut.id)],
            "start_at": local(MONDAY, 12).isoformat(),
        },
    )
    assert held.json()["quote"]["max_bonus_spend"] == 30_000
    await client.delete(f"{MINI}/holds/{held.json()['hold_id']}", headers=alice)

    too_much = await book(client, alice, world, local(MONDAY, 12), bonus=30_001)
    assert too_much.json()["error"]["code"] == "bonus_limit"

    first = await book(client, alice, world, local(MONDAY, 12), bonus=30_000)
    assert first.status_code == 201, first.text
    assert first.json()["total_due"] == 70_000
    assert (await client.get(f"{MINI}/me", headers=alice)).json()["bonus_balance"] == 20_000

    # cancel → bonuses back
    clock[0] = NOW + timedelta(seconds=30)
    cancel = await client.post(
        f"{MINI}/bookings/{first.json()['id']}/cancel", headers=alice, json={}
    )
    assert cancel.status_code == 200
    assert (await client.get(f"{MINI}/me", headers=alice)).json()["bonus_balance"] == 50_000
    clock[0] = NOW + timedelta(minutes=1)  # distinct timestamps keep the history order stable

    # second booking with bonuses, completed: cashback on the money part only
    second = await book(client, alice, world, local(MONDAY, 15), bonus=10_000)
    assert second.status_code == 201
    clock[0] = local(MONDAY, 16, 30)
    done = await complete(owner_client, second.json())
    assert done.status_code == 200, done.text
    assert done.json()["paid_amount"] == 90_000

    summary = (await client.get(f"{MINI}/bonus", headers=alice)).json()
    # default levels: Bronze 3% from the first visit → 3% of 90 000 = 2 700
    assert summary["level"]["name_i18n"]["ru"] == "Бронза"
    assert summary["balance"] == 50_000 - 10_000 + 2_700
    assert summary["next_level"]["name_i18n"]["ru"] == "Серебро"
    assert summary["visits_left"] == 4
    assert summary["spent_left"] == 1_000_000 - 90_000

    history = (
        await client.get(f"{MINI}/bonus/transactions", headers=alice, params={"limit": 3})
    ).json()
    assert [tx["type"] for tx in history["items"]] == ["earn", "spend", "refund"]
    assert history["next_cursor"]
    rest = (
        await client.get(
            f"{MINI}/bonus/transactions", headers=alice, params={"cursor": history["next_cursor"]}
        )
    ).json()
    assert [tx["type"] for tx in rest["items"]] == ["spend", "welcome"]

    templates = (await session.execute(select(TelegramOutbox.template_key))).scalars().all()
    assert "bonus_credited_client" in templates  # welcome
    assert "bonus_earned_client" in templates

    db_client = await session.scalar(select(Client).where(Client.phone == "+996700001001"))
    assert db_client is not None
    assert db_client.visits_count == 1
    assert db_client.total_spent == 90_000
    assert await BonusLedger(session).ledger_sum(db_client.id) == db_client.bonus_balance


async def test_level_upgrade_by_spent_with_any_rule(
    client: httpx.AsyncClient,
    owner_client: httpx.AsyncClient,
    world: World,
    session: AsyncSession,
    clock: list[datetime],
) -> None:
    alice = await register(client, 2001)
    booking = await book(client, alice, world, local(MONDAY, 12))
    clock[0] = local(MONDAY, 13, 30)
    # paid 10 000 сом at once → Silver (min_spent 1 000 000 tyiyn) with level_rule=any
    assert (await complete(owner_client, booking.json(), paid=1_000_000)).status_code == 200
    summary = (await client.get(f"{MINI}/bonus", headers=alice)).json()
    assert summary["level"]["name_i18n"]["ru"] == "Серебро"
    # cashback uses the level reached by this visit: 5% of 1 000 000
    assert summary["balance"] == 50_000 + 50_000


async def test_referral_rewards_after_first_visit_only(
    client: httpx.AsyncClient,
    owner_client: httpx.AsyncClient,
    world: World,
    session: AsyncSession,
    clock: list[datetime],
) -> None:
    referrer = await register(client, 3001)
    code = (await client.get(f"{MINI}/me", headers=referrer)).json()["referral_code"]
    invited = await register(client, 3002, start_param=f"ref_{code}")

    referral = (await client.get(f"{MINI}/referral", headers=referrer)).json()
    assert referral["invited"] == 1
    assert referral["rewarded"] == 0
    assert referral["miniapp_link"].endswith(f"?startapp=ref_{code}")

    first = await book(client, invited, world, local(MONDAY, 12))
    second = await book(client, invited, world, local(MONDAY, 15))
    clock[0] = local(MONDAY, 18)
    await complete(owner_client, first.json())
    await complete(owner_client, second.json())

    referrer_me = (await client.get(f"{MINI}/me", headers=referrer)).json()
    assert referrer_me["bonus_balance"] == 50_000 + 30_000, "rewarded once"
    invited_me = (await client.get(f"{MINI}/me", headers=invited)).json()
    # welcome 50k + referee 10k + 3% cashback of two visits (100k each, Bronze)
    assert invited_me["bonus_balance"] == 50_000 + 10_000 + 3_000 + 3_000
    assert (await client.get(f"{MINI}/referral", headers=referrer)).json()["rewarded"] == 1


async def test_no_show_refunds_and_revival_pays_full(
    client: httpx.AsyncClient,
    owner_client: httpx.AsyncClient,
    world: World,
    clock: list[datetime],
) -> None:
    alice = await register(client, 4001)
    booking = (await book(client, alice, world, local(MONDAY, 12), bonus=20_000)).json()
    detail = (await owner_client.get(f"{ADMIN}/bookings/{booking['id']}")).json()
    no_show = await owner_client.post(
        f"{ADMIN}/bookings/{booking['id']}/status",
        json={"version": detail["version"], "status": "no_show"},
    )
    assert no_show.status_code == 200
    assert (await client.get(f"{MINI}/me", headers=alice)).json()["bonus_balance"] == 50_000

    revived = await owner_client.post(
        f"{ADMIN}/bookings/{booking['id']}/status",
        json={"version": no_show.json()["version"], "status": "confirmed"},
    )
    assert revived.json()["bonus_spent"] == 0
    assert revived.json()["total_due"] == 100_000


async def test_admin_price_cut_returns_excess_bonuses(
    client: httpx.AsyncClient,
    owner_client: httpx.AsyncClient,
    world: World,
    clock: list[datetime],
) -> None:
    alice = await register(client, 5001)
    booking = (await book(client, alice, world, local(MONDAY, 12), bonus=30_000)).json()
    detail = (await owner_client.get(f"{ADMIN}/bookings/{booking['id']}")).json()
    patched = await owner_client.patch(
        f"{ADMIN}/bookings/{booking['id']}",
        json={
            "version": detail["version"],
            "services": [{"service_id": str(world.haircut.id), "price": 20_000}],
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["bonus_spent"] == 20_000
    assert patched.json()["total_due"] == 0
    assert (await client.get(f"{MINI}/me", headers=alice)).json()["bonus_balance"] == 30_000


async def test_bonuses_disabled(
    client: httpx.AsyncClient,
    world: World,
    session: AsyncSession,
    bonus_on: BonusSettings,
    clock: list[datetime],
) -> None:
    bonus_on.enabled = False
    await session.commit()
    alice = await register(client, 6001)
    assert (await client.get(f"{MINI}/me", headers=alice)).json()["bonus_balance"] == 0
    response = await book(client, alice, world, local(MONDAY, 12), bonus=1)
    assert response.json()["error"]["code"] == "bonus_limit"


# ---------------------------------------------------------------------------
# jobs: birthdays, expiry warnings
# ---------------------------------------------------------------------------


async def test_birthday_bonus_once_per_year(
    session: AsyncSession, branch: Branch, bonus_on: BonusSettings
) -> None:
    bonus_on.birthday_enabled = True
    bonus_on.birthday_amount = 25_000
    bonus_on.birthday_days_before = 2
    await session.commit()
    hero = await make_client(session, branch, "Именинник")
    hero.birthday = date(1995, 12, 9)
    other = await make_client(session, branch, "Другой")
    other.birthday = date(1995, 6, 1)
    await session.commit()

    service = BonusService(session)
    assert await service.birthdays(NOW) == 1  # Dec 7 = 2 days before Dec 9
    await session.commit()
    assert await service.birthdays(NOW + timedelta(hours=5)) == 0
    await session.commit()
    balance = await session.scalar(select(Client.bonus_balance).where(Client.id == hero.id))
    assert balance == 25_000


async def test_expiry_warning_once_per_day(
    session: AsyncSession,
    branch: Branch,
    bonus_on: BonusSettings,
    client: httpx.AsyncClient,
) -> None:
    await register(client, 7001)
    target = await session.scalar(select(Client).where(Client.phone == "+996700007001"))
    assert target is not None
    ledger = BonusLedger(session)
    locked = await ledger.lock_client(target.id)
    await ledger.credit(
        locked, BonusTxType.MANUAL, 10_000, NOW, comment="x", expires_at=NOW + timedelta(days=2)
    )
    await session.commit()

    service = BonusService(session)
    assert await service.warn_expiring(NOW) == 1
    await session.commit()
    await service.warn_expiring(NOW + timedelta(hours=1))
    await session.commit()
    rows = (
        (
            await session.execute(
                select(TelegramOutbox).where(TelegramOutbox.template_key == "bonus_expiring_client")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].payload["date"] == "09.12.2026"


async def test_level_delete_keeps_clients(
    session: AsyncSession, branch: Branch, bonus_on: BonusSettings
) -> None:
    level = await session.scalar(select(LoyaltyLevel).where(LoyaltyLevel.branch_id == branch.id))
    assert level is not None
    member = await make_client(session, branch)
    member.level_id = level.id
    await session.commit()
    await session.delete(level)
    await session.commit()
    await session.refresh(member)
    assert member.level_id is None
