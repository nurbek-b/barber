from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI
from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_now
from app.core.security.tokens import REFRESH_COOKIE
from app.models import (
    Barber,
    BarberSchedule,
    Booking,
    BookingService,
    Branch,
    Client,
    User,
)
from app.models.enums import AdminRole, BookingStatus, PaymentMethod
from tests.conftest import AdminFactory, login_as, tma_header

TZ = ZoneInfo("Asia/Bishkek")
TODAY = date(2026, 12, 7)
ADMIN = "/api/v1/admin"


def local(day: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=TZ).astimezone(UTC)


@pytest.fixture
def clock(app: FastAPI) -> Iterator[None]:
    app.dependency_overrides[get_now] = lambda: local(TODAY, 18)
    yield
    app.dependency_overrides.pop(get_now, None)


async def seed_client(
    session: AsyncSession,
    branch: Branch,
    name: str,
    phone: str,
    username: str | None = None,
    tags: list[str] | None = None,
) -> Client:
    user = None
    if username:
        user = User(telegram_id=abs(hash(username)) % 10**9, first_name=name, username=username)
        session.add(user)
        await session.flush()
    client = Client(
        branch_id=branch.id,
        name=name,
        phone=phone,
        user_id=user.id if user else None,
        referral_code=phone[-8:],
        tags=tags or [],
    )
    session.add(client)
    await session.commit()
    return client


# ---------------------------------------------------------------------------
# clients
# ---------------------------------------------------------------------------


async def test_client_search_and_filters(
    owner_client: httpx.AsyncClient, session: AsyncSession, branch: Branch
) -> None:
    await seed_client(session, branch, "Айбек", "+996555111222", "aibek_kg", ["vip"])
    await seed_client(session, branch, "Бакыт", "+996700333444", tags=["student"])
    await seed_client(session, branch, "Chris", "+996777555666")

    async def names(**params: str) -> list[str]:
        response = await owner_client.get(
            f"{ADMIN}/clients", params={"sort": "name", "desc": "false", **params}
        )
        assert response.status_code == 200, response.text
        return [item["name"] for item in response.json()["items"]]

    assert await names() == ["Chris", "Айбек", "Бакыт"]
    assert await names(q="айб") == ["Айбек"]
    assert await names(q="aibek") == ["Айбек"]
    assert await names(q="700 333") == ["Бакыт"]
    assert await names(q="%") == []
    assert await names(tag="VIP") == ["Айбек"]
    page = (await owner_client.get(f"{ADMIN}/clients", params={"limit": 2})).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2


async def test_client_crud_and_block(
    owner_client: httpx.AsyncClient,
    client: httpx.AsyncClient,
    session: AsyncSession,
    branch: Branch,
    clock: None,
) -> None:
    created = await owner_client.post(
        f"{ADMIN}/clients",
        json={
            "name": "Звонок",
            "phone": "0555 12 34 56",
            "tags": ["VIP ", "vip"],
            "notes": "любит кофе",
        },
    )
    assert created.status_code == 201, created.text
    card = created.json()
    assert card["phone"] == "+0555123456"
    assert card["tags"] == ["vip"]
    duplicate = await owner_client.post(
        f"{ADMIN}/clients", json={"name": "X", "phone": "0555123456"}
    )
    assert duplicate.status_code == 409

    patched = await owner_client.patch(
        f"{ADMIN}/clients/{card['id']}", json={"birthday": "1990-05-01", "tags": ["regular"]}
    )
    assert patched.json()["birthday"] == "1990-05-01"
    assert patched.json()["tags"] == ["regular"]

    # blocking a Telegram client locks them out of the Mini App
    await client.get("/api/v1/miniapp/me", headers=tma_header(4242))
    tg_client = (await owner_client.get(f"{ADMIN}/clients", params={"q": "Бек"})).json()["items"][0]
    blocked = await owner_client.post(
        f"{ADMIN}/clients/{tg_client['id']}/block", json={"blocked": True, "reason": "хамство"}
    )
    assert blocked.json()["is_blocked"] is True
    assert (await client.get("/api/v1/miniapp/me", headers=tma_header(4242))).status_code == 403
    await owner_client.post(f"{ADMIN}/clients/{tg_client['id']}/block", json={"blocked": False})
    assert (await client.get("/api/v1/miniapp/me", headers=tma_header(4242))).status_code == 200


async def test_barber_cannot_read_clients(
    client: httpx.AsyncClient, make_admin: AdminFactory
) -> None:
    await login_as(client, await make_admin(AdminRole.BARBER))
    assert (await client.get(f"{ADMIN}/clients")).status_code == 403


# ---------------------------------------------------------------------------
# salon settings
# ---------------------------------------------------------------------------


async def test_salon_settings(owner_client: httpx.AsyncClient) -> None:
    current = (await owner_client.get(f"{ADMIN}/settings/salon")).json()
    assert current["timezone"] == "Asia/Bishkek"
    body = {
        **current,
        "buffer_min": 10,
        "reminder_offsets_min": [120, 1440, 120],
        "notification_templates": {"reminder_client": {"ru": "Ждём вас {when}"}},
    }
    updated = await owner_client.put(f"{ADMIN}/settings/salon", json=body)
    assert updated.status_code == 200, updated.text
    assert updated.json()["reminder_offsets_min"] == [1440, 120]
    assert updated.json()["buffer_min"] == 10

    for bad in (
        {**current, "timezone": "Mars/Base"},
        {**current, "notification_templates": {"nope": {"ru": "x"}}},
        {**current, "slot_step_min": 1},
    ):
        assert (await owner_client.put(f"{ADMIN}/settings/salon", json=bad)).status_code == 422
    defaults = (await owner_client.get(f"{ADMIN}/settings/notification-templates")).json()
    assert "booking_created_admin" in defaults["templates"]


# ---------------------------------------------------------------------------
# staff & audit
# ---------------------------------------------------------------------------


async def test_staff_management(
    owner_client: httpx.AsyncClient,
    client: httpx.AsyncClient,
    session: AsyncSession,
    branch: Branch,
    make_admin: AdminFactory,
    app: FastAPI,
) -> None:
    barber = Barber(branch_id=branch.id, name="Мастер")
    session.add(barber)
    await session.commit()

    no_barber = await owner_client.post(
        f"{ADMIN}/admin-users",
        json={"login": "m1", "password": "long-password-1", "role": "barber"},
    )
    assert no_barber.status_code == 422
    created = await owner_client.post(
        f"{ADMIN}/admin-users",
        json={
            "login": "Master1",
            "password": "long-password-1",
            "role": "barber",
            "barber_id": str(barber.id),
            "full_name": "Мастер",
        },
    )
    assert created.status_code == 201, created.text
    account = created.json()
    assert account["login"] == "master1"
    second = await owner_client.post(
        f"{ADMIN}/admin-users",
        json={
            "login": "master2",
            "password": "long-password-1",
            "role": "barber",
            "barber_id": str(barber.id),
        },
    )
    assert second.json()["error"]["code"] == "barber_has_account"

    # the new barber logs in; a password reset signs them out everywhere
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as other:
        response = await other.post(
            f"{ADMIN}/auth/login", json={"login": "master1", "password": "long-password-1"}
        )
        assert response.status_code == 200
        reset = await owner_client.patch(
            f"{ADMIN}/admin-users/{account['id']}", json={"password": "another-password-2"}
        )
        assert reset.status_code == 200
        other.cookies.set(REFRESH_COOKIE, other.cookies[REFRESH_COOKIE], path="/api/v1/admin/auth")
        assert (await other.post(f"{ADMIN}/auth/refresh")).status_code == 401

    me = (await owner_client.get(f"{ADMIN}/auth/me")).json()
    lockout = await owner_client.patch(f"{ADMIN}/admin-users/{me['id']}", json={"is_active": False})
    assert lockout.json()["error"]["code"] == "self_lockout"
    listed = (await owner_client.get(f"{ADMIN}/admin-users")).json()
    assert {item["login"] for item in listed} >= {"master1", me["login"]}

    audit = (await owner_client.get(f"{ADMIN}/audit-log", params={"action": "staff."})).json()
    assert [item["action"] for item in audit["items"]] == ["staff.update", "staff.create"]
    assert audit["items"][0]["after"]["password"] == "changed"
    assert "password_hash" not in str(audit)

    await login_as(client, await make_admin(AdminRole.ADMIN))
    assert (await client.get(f"{ADMIN}/admin-users")).status_code == 403
    assert (await client.get(f"{ADMIN}/audit-log")).status_code == 403


# ---------------------------------------------------------------------------
# dashboard & finance
# ---------------------------------------------------------------------------


async def _finance_world(session: AsyncSession, branch: Branch) -> tuple[Barber, Barber]:
    first = Barber(branch_id=branch.id, name="Первый", sort_order=1)
    second = Barber(branch_id=branch.id, name="Второй", sort_order=2)
    session.add_all([first, second])
    await session.flush()
    for barber in (first, second):
        session.add_all(
            BarberSchedule(barber_id=barber.id, weekday=d, start_time=time(10), end_time=time(20))
            for d in range(7)
        )
    customer = Client(
        branch_id=branch.id, name="Клиент", phone="+996700000001", referral_code="finance1"
    )
    session.add(customer)
    await session.flush()

    def booking(
        barber: Barber,
        start: datetime,
        subtotal: int,
        bonus: int,
        paid: int | None,
        status: BookingStatus,
        method: PaymentMethod | None,
        name: str,
    ) -> Booking:
        return Booking(
            branch_id=branch.id,
            client_id=customer.id,
            barber_id=barber.id,
            status=status,
            start_at=start,
            end_at=start + timedelta(hours=1),
            blocked_until=start + timedelta(hours=1),
            subtotal=subtotal,
            bonus_spent=bonus,
            total_due=subtotal - bonus,
            paid_amount=paid,
            payment_method=method,
            services=[BookingService(name_snapshot={"ru": name}, duration_min=60, price=subtotal)],
        )

    session.add_all(
        [
            booking(
                first,
                local(TODAY, 10),
                100_000,
                20_000,
                80_000,
                BookingStatus.COMPLETED,
                PaymentMethod.CASH,
                "Стрижка",
            ),
            booking(
                first,
                local(TODAY, 12),
                50_000,
                0,
                50_000,
                BookingStatus.COMPLETED,
                PaymentMethod.CARD,
                "Борода",
            ),
            booking(
                second,
                local(TODAY, 11),
                100_000,
                0,
                100_000,
                BookingStatus.COMPLETED,
                PaymentMethod.CARD,
                "Стрижка",
            ),
            booking(
                second, local(TODAY, 19), 100_000, 0, None, BookingStatus.CONFIRMED, None, "Стрижка"
            ),
            booking(
                first, local(TODAY, 14), 100_000, 0, None, BookingStatus.CANCELLED, None, "Стрижка"
            ),
            booking(
                first,
                local(TODAY - timedelta(days=3), 12),
                70_000,
                0,
                70_000,
                BookingStatus.COMPLETED,
                PaymentMethod.CASH,
                "Стрижка",
            ),
        ]
    )
    await session.commit()
    return first, second


async def test_dashboard(
    owner_client: httpx.AsyncClient, session: AsyncSession, branch: Branch, clock: None
) -> None:
    first, second = await _finance_world(session, branch)
    data = (await owner_client.get(f"{ADMIN}/dashboard")).json()
    assert data["today"] == "2026-12-07"
    assert data["bookings_today"] == 4  # cancelled not counted
    assert data["bookings_today_by_status"] == {"completed": 3, "confirmed": 1, "cancelled": 1}
    assert data["revenue_day"] == 230_000
    assert data["revenue_week"] == 230_000  # Monday
    assert data["revenue_month"] == 300_000
    assert data["average_check"] == 75_000
    load = {item["name"]: item for item in data["barbers"]}
    assert load["Первый"]["booked_minutes"] == 120
    assert load["Первый"]["working_minutes"] == 600
    assert load["Первый"]["load_percent"] == 20
    assert load["Второй"]["bookings"] == 2
    assert len(data["revenue_chart"]) == 30
    assert data["revenue_chart"][-1] == {"date": "2026-12-07", "revenue": 230_000, "bookings": 3}
    assert [item["barber"] for item in data["upcoming"]] == ["Второй"]  # 19:00, after "now"
    del first, second


async def test_finance_report_and_exports(
    owner_client: httpx.AsyncClient, session: AsyncSession, branch: Branch, clock: None
) -> None:
    await _finance_world(session, branch)
    params = {"date_from": "2026-12-01", "date_to": "2026-12-07"}
    report = (await owner_client.get(f"{ADMIN}/finance/report", params=params)).json()
    assert report["totals"] == {
        "bookings": 4,
        "subtotal": 320_000,
        "bonus_spent": 20_000,
        "total_due": 300_000,
        "paid": 300_000,
        "master_share": 0,  # no commission rates set
    }
    by_barber = {item["name"]: item["paid"] for item in report["by_barber"]}
    assert by_barber == {"Первый": 200_000, "Второй": 100_000}
    services = {
        item["name_i18n"]["ru"]: (item["count"], item["revenue"]) for item in report["by_service"]
    }
    assert services == {"Стрижка": (3, 270_000), "Борода": (1, 50_000)}
    methods = {item["payment_method"]: item["paid"] for item in report["by_payment_method"]}
    assert methods == {"cash": 150_000, "card": 150_000}

    csv_response = await owner_client.get(
        f"{ADMIN}/finance/export", params={**params, "format": "csv"}
    )
    assert csv_response.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(csv_response.content.decode("utf-8-sig")), delimiter=";"))
    assert rows[0][:3] == ["Дата", "Мастер", "Клиент"]
    assert len(rows) == 5
    assert rows[1][4] == "700.00"  # Dec 4, earliest first, no float artefacts

    xlsx = await owner_client.get(f"{ADMIN}/finance/export", params={**params, "format": "xlsx"})
    assert 'filename="finance_2026-12-01_2026-12-07.xlsx"' in xlsx.headers["content-disposition"]
    workbook = load_workbook(io.BytesIO(xlsx.content))
    assert workbook.sheetnames == ["Визиты", "Мастера"]
    assert workbook["Мастера"]["G1"].value == "Мастеру"
    assert workbook["Визиты"].max_row == 5

    bad = await owner_client.get(
        f"{ADMIN}/finance/report", params={"date_from": "2026-12-07", "date_to": "2026-01-01"}
    )
    assert bad.status_code == 422


async def test_barber_has_no_finance(client: httpx.AsyncClient, make_admin: AdminFactory) -> None:
    await login_as(client, await make_admin(AdminRole.BARBER))
    assert (await client.get(f"{ADMIN}/dashboard")).status_code == 403
    assert (
        await client.get(
            f"{ADMIN}/finance/report", params={"date_from": "2026-12-01", "date_to": "2026-12-02"}
        )
    ).status_code == 403
