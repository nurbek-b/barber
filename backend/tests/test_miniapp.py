from __future__ import annotations

import json
import time
from datetime import time as clock_time

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.initdata import build_init_data
from app.models import Barber, BarberSchedule, BarberService, Branch, Client, Service, User
from tests.conftest import BOT_TOKEN, tma_header

API = "/api/v1/miniapp"


async def test_requires_init_data(client: httpx.AsyncClient, branch: Branch) -> None:
    assert (await client.get(f"{API}/me")).status_code == 401
    bad = await client.get(f"{API}/me", headers={"Authorization": "Bearer something"})
    assert bad.status_code == 401
    forged = await client.get(f"{API}/me", headers=tma_header(bot_token="1:other"))
    assert forged.status_code == 401
    assert forged.json()["error"]["code"] == "init_data_invalid"
    expired = await client.get(
        f"{API}/me", headers=tma_header(auth_date=int(time.time()) - 2 * 86400)
    )
    assert expired.status_code == 401


async def test_first_call_registers_client(
    client: httpx.AsyncClient, branch: Branch, session: AsyncSession
) -> None:
    first = await client.get(f"{API}/me", headers=tma_header(1001, language_code="ky"))
    assert first.status_code == 200
    body = first.json()
    assert body["is_new"] is True
    assert body["telegram_id"] == 1001
    assert body["language"] == "ky"
    assert body["bonus_balance"] == 0
    assert len(body["referral_code"]) == 8

    second = await client.get(f"{API}/me", headers=tma_header(1001))
    assert second.json()["is_new"] is False
    assert second.json()["id"] == body["id"]

    count = len((await session.execute(select(Client))).scalars().all())
    assert count == 1


async def test_unsupported_language_falls_back_to_salon_default(
    client: httpx.AsyncClient, branch: Branch
) -> None:
    response = await client.get(f"{API}/me", headers=tma_header(1002, language_code="de"))
    assert response.json()["language"] == "ru"


async def test_referral_start_param(
    client: httpx.AsyncClient, branch: Branch, session: AsyncSession
) -> None:
    referrer = (await client.get(f"{API}/me", headers=tma_header(2001))).json()
    code = referrer["referral_code"]

    await client.get(f"{API}/me", headers=tma_header(2002, start_param=f"ref_{code}"))
    invited = await session.scalar(
        select(Client).join(User, User.id == Client.user_id).where(User.telegram_id == 2002)
    )
    assert invited is not None
    assert str(invited.referred_by_client_id) == referrer["id"]

    # existing clients cannot be "re-referred"
    again = await client.get(f"{API}/me", headers=tma_header(2001, start_param=f"ref_{code}"))
    assert again.status_code == 200
    me = await session.get(Client, referrer["id"])
    assert me is not None
    assert me.referred_by_client_id is None


async def test_blocked_client(
    client: httpx.AsyncClient, branch: Branch, session: AsyncSession
) -> None:
    me = (await client.get(f"{API}/me", headers=tma_header(3001))).json()
    db_client = await session.get(Client, me["id"])
    assert db_client is not None
    db_client.is_blocked = True
    await session.commit()
    response = await client.get(f"{API}/me", headers=tma_header(3001))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "client_blocked"


async def test_update_profile_and_birthday_lock(client: httpx.AsyncClient, branch: Branch) -> None:
    headers = tma_header(4001)
    updated = await client.patch(
        f"{API}/me",
        headers=headers,
        json={"name": "Бектур", "language": "en", "birthday": "1995-05-20"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Бектур"
    assert updated.json()["language"] == "en"

    locked = await client.patch(f"{API}/me", headers=headers, json={"birthday": "1990-01-01"})
    assert locked.status_code == 422
    assert locked.json()["error"]["code"] == "birthday_locked"

    bad_lang = await client.patch(f"{API}/me", headers=headers, json={"language": "fr"})
    assert bad_lang.status_code == 422


def _contact(user_id: int, phone: str) -> str:
    return build_init_data(
        {
            "contact": json.dumps({"user_id": user_id, "phone_number": phone, "first_name": "B"}),
            "auth_date": str(int(time.time())),
        },
        BOT_TOKEN,
    )


async def test_save_phone_from_signed_contact(client: httpx.AsyncClient, branch: Branch) -> None:
    headers = tma_header(5001)
    response = await client.post(
        f"{API}/me/phone", headers=headers, json={"contact": _contact(5001, "996 555 12-34-56")}
    )
    assert response.status_code == 200
    assert response.json()["phone"] == "+996555123456"

    foreign = await client.post(
        f"{API}/me/phone", headers=headers, json={"contact": _contact(9999, "996700000000")}
    )
    assert foreign.status_code == 403

    tampered = _contact(5001, "996555123456").replace("996555123456", "996700000000")
    response = await client.post(f"{API}/me/phone", headers=headers, json={"contact": tampered})
    assert response.status_code == 422


async def _seed_catalog(session: AsyncSession, branch: Branch) -> dict[str, object]:
    haircut = Service(
        branch_id=branch.id, name_i18n={"ru": "Стрижка"}, duration_min=45, base_price=80_000
    )
    beard = Service(
        branch_id=branch.id, name_i18n={"ru": "Борода"}, duration_min=30, base_price=50_000
    )
    hidden = Service(
        branch_id=branch.id,
        name_i18n={"ru": "Старое"},
        duration_min=30,
        base_price=1,
        is_active=False,
    )
    senior = Barber(branch_id=branch.id, name="Senior", sort_order=1)
    junior = Barber(branch_id=branch.id, name="Junior", sort_order=2)
    offline = Barber(branch_id=branch.id, name="Offline", is_bookable_online=False)
    session.add_all([haircut, beard, hidden, senior, junior, offline])
    await session.flush()
    session.add_all(
        [
            BarberService(
                barber_id=senior.id, service_id=haircut.id, price=120_000, duration_min=60
            ),
            BarberService(barber_id=senior.id, service_id=beard.id),
            BarberService(barber_id=senior.id, service_id=hidden.id),
            BarberService(barber_id=junior.id, service_id=haircut.id),
            BarberService(barber_id=offline.id, service_id=beard.id, price=1),
            # barbers without weekly hours are hidden from clients
            *(
                BarberSchedule(
                    barber_id=b.id, weekday=0, start_time=clock_time(10), end_time=clock_time(18)
                )
                for b in (senior, junior, offline)
            ),
        ]
    )
    await session.commit()
    return {
        "haircut": haircut,
        "beard": beard,
        "senior": senior,
        "junior": junior,
        "offline": offline,
    }


async def test_public_barbers(
    client: httpx.AsyncClient, branch: Branch, session: AsyncSession
) -> None:
    data = await _seed_catalog(session, branch)
    headers = tma_header()

    all_barbers = await client.get(f"{API}/barbers", headers=headers)
    assert [item["name"] for item in all_barbers.json()] == ["Senior", "Junior"]

    haircut, beard = data["haircut"], data["beard"]
    assert isinstance(haircut, Service)
    assert isinstance(beard, Service)
    both = await client.get(
        f"{API}/barbers",
        headers=headers,
        params=[("service_ids", str(haircut.id)), ("service_ids", str(beard.id))],
    )
    assert [item["name"] for item in both.json()] == ["Senior"]


async def test_public_services_any_barber_ranges(
    client: httpx.AsyncClient, branch: Branch, session: AsyncSession
) -> None:
    await _seed_catalog(session, branch)
    response = await client.get(f"{API}/services", headers=tma_header())
    services = {item["name_i18n"]["ru"]: item for item in response.json()["services"]}
    assert set(services) == {"Стрижка", "Борода"}, "inactive and offline-only are hidden"
    assert services["Стрижка"]["price_min"] == 80_000
    assert services["Стрижка"]["price_max"] == 120_000
    assert services["Стрижка"]["duration_min"] == 45
    assert services["Стрижка"]["duration_max_min"] == 60
    assert services["Борода"]["price_min"] == services["Борода"]["price_max"] == 50_000


async def test_public_services_for_barber(
    client: httpx.AsyncClient, branch: Branch, session: AsyncSession
) -> None:
    data = await _seed_catalog(session, branch)
    senior, offline = data["senior"], data["offline"]
    assert isinstance(senior, Barber)
    assert isinstance(offline, Barber)

    response = await client.get(
        f"{API}/services", headers=tma_header(), params={"barber_id": str(senior.id)}
    )
    services = {item["name_i18n"]["ru"]: item for item in response.json()["services"]}
    assert services["Стрижка"]["price_min"] == services["Стрижка"]["price_max"] == 120_000

    hidden = await client.get(
        f"{API}/services", headers=tma_header(), params={"barber_id": str(offline.id)}
    )
    assert hidden.status_code == 404


async def test_salon_settings(client: httpx.AsyncClient, branch: Branch) -> None:
    response = await client.get(f"{API}/salon", headers=tma_header())
    body = response.json()
    assert body["timezone"] == "Asia/Bishkek"
    assert body["currency"] == "KGS"
    assert body["name"] == "Test Barbershop"


async def test_not_configured_salon(client: httpx.AsyncClient) -> None:
    response = await client.get(f"{API}/me", headers=tma_header())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "salon_not_configured"
