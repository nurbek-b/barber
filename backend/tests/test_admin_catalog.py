from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import AuditLog, Barber
from app.models.enums import AdminRole
from tests.conftest import AdminFactory, login_as

API = "/api/v1/admin"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


async def _service(http: httpx.AsyncClient, name: str, duration: int, price: int) -> str:
    response = await http.post(
        f"{API}/services",
        json={"name_i18n": {"ru": name}, "duration_min": duration, "base_price": price},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_category_and_service_crud(
    owner_client: httpx.AsyncClient, session: AsyncSession
) -> None:
    category = await owner_client.post(
        f"{API}/service-categories",
        json={"name_i18n": {"ru": "Стрижки", "ky": "Чач кырктыруу", "en": "Haircuts"}},
    )
    assert category.status_code == 201
    category_id = category.json()["id"]

    created = await owner_client.post(
        f"{API}/services",
        json={
            "category_id": category_id,
            "name_i18n": {"ru": "Мужская стрижка", "en": "Men's haircut"},
            "duration_min": 45,
            "base_price": 80_000,
        },
    )
    assert created.status_code == 201
    service = created.json()
    assert service["base_price"] == 80_000
    assert service["is_active"] is True

    patched = await owner_client.patch(
        f"{API}/services/{service['id']}", json={"base_price": 90_000, "category_id": None}
    )
    assert patched.status_code == 200
    assert patched.json()["base_price"] == 90_000
    assert patched.json()["category_id"] is None

    listed = await owner_client.get(f"{API}/services")
    assert listed.json()["total"] == 1

    assert (await owner_client.delete(f"{API}/services/{service['id']}")).status_code == 204
    active = await owner_client.get(f"{API}/services", params={"only_active": True})
    assert active.json()["total"] == 0

    actions = (await session.execute(select(AuditLog.action).order_by(AuditLog.id))).scalars()
    assert list(actions)[-3:] == ["service.create", "service.update", "service.deactivate"]

    update_entry = await session.scalar(select(AuditLog).where(AuditLog.action == "service.update"))
    assert update_entry is not None
    assert update_entry.before == {"base_price": 80_000, "category_id": category_id}
    assert update_entry.after == {"base_price": 90_000, "category_id": None}


async def test_service_validation(owner_client: httpx.AsyncClient) -> None:
    no_ru = await owner_client.post(
        f"{API}/services",
        json={"name_i18n": {"en": "Haircut"}, "duration_min": 30, "base_price": 100},
    )
    assert no_ru.status_code == 422
    assert no_ru.json()["error"]["code"] == "validation_error"

    for bad in (
        {"name_i18n": {"ru": "X"}, "duration_min": 3, "base_price": 100},
        {"name_i18n": {"ru": "X"}, "duration_min": 30, "base_price": -1},
        {"name_i18n": {"ru": "X"}, "duration_min": 30, "base_price": 10.5},
        {"name_i18n": {"ru": "X", "de": "Y"}, "duration_min": 30, "base_price": 100},
    ):
        assert (await owner_client.post(f"{API}/services", json=bad)).status_code == 422


async def test_barber_with_service_overrides(owner_client: httpx.AsyncClient) -> None:
    haircut = await _service(owner_client, "Стрижка", 45, 80_000)
    beard = await _service(owner_client, "Борода", 30, 50_000)

    created = await owner_client.post(
        f"{API}/barbers",
        json={
            "name": "Азамат",
            "specialization_i18n": {"ru": "Фейды", "en": "Fades"},
            "services": [
                {"service_id": haircut, "price": 120_000, "duration_min": 60},
                {"service_id": beard},
            ],
        },
    )
    assert created.status_code == 201, created.text
    barber = created.json()
    by_id = {item["service_id"]: item for item in barber["services"]}
    assert by_id[haircut]["effective_price"] == 120_000
    assert by_id[haircut]["effective_duration_min"] == 60
    assert by_id[beard]["effective_price"] == 50_000
    assert by_id[beard]["price"] is None
    assert barber["rating"] is None

    replaced = await owner_client.put(
        f"{API}/barbers/{barber['id']}/services", json={"services": [{"service_id": beard}]}
    )
    assert replaced.status_code == 200
    assert [item["service_id"] for item in replaced.json()] == [beard]

    patched = await owner_client.patch(f"{API}/barbers/{barber['id']}", json={"name": "Азамат Б."})
    assert patched.json()["name"] == "Азамат Б."

    assert (await owner_client.delete(f"{API}/barbers/{barber['id']}")).status_code == 204
    detail = await owner_client.get(f"{API}/barbers/{barber['id']}")
    assert detail.json()["is_active"] is False
    assert detail.json()["is_bookable_online"] is False


async def test_barber_rejects_unknown_or_duplicate_services(
    owner_client: httpx.AsyncClient,
) -> None:
    haircut = await _service(owner_client, "Стрижка", 45, 80_000)
    unknown = "00000000-0000-0000-0000-000000000001"
    response = await owner_client.post(
        f"{API}/barbers", json={"name": "X", "services": [{"service_id": unknown}]}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "service_not_found"

    duplicate = await owner_client.post(
        f"{API}/barbers",
        json={"name": "X", "services": [{"service_id": haircut}, {"service_id": haircut}]},
    )
    assert duplicate.status_code == 422


async def test_not_found_format(owner_client: httpx.AsyncClient) -> None:
    response = await owner_client.get(f"{API}/barbers/00000000-0000-0000-0000-000000000009")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_photo_upload(
    owner_client: httpx.AsyncClient,
    make_barber: Callable[..., Awaitable[Barber]],
    settings: Settings,
) -> None:
    barber = await make_barber()
    url = f"{API}/barbers/{barber.id}/photo"

    first = await owner_client.post(url, files={"file": ("a.png", PNG, "image/png")})
    assert first.status_code == 200, first.text
    first_url = first.json()["photo_url"]
    assert first_url.startswith("/media/barbers/")
    first_file = Path(settings.media_dir) / "barbers" / first_url.rsplit("/", 1)[1]
    assert first_file.exists()

    second = await owner_client.post(url, files={"file": ("b.png", PNG, "image/png")})
    assert second.status_code == 200
    assert not first_file.exists(), "previous photo must be removed"

    fake = await owner_client.post(
        url, files={"file": ("evil.png", b"<?php echo 1; ?>", "image/png")}
    )
    assert fake.status_code == 422
    assert fake.json()["error"]["code"] == "unsupported_image"

    huge = await owner_client.post(
        url, files={"file": ("big.png", PNG + b"0" * settings.max_upload_bytes, "image/png")}
    )
    assert huge.status_code == 413


# ---------------- RBAC ----------------


async def test_barber_role_sees_only_self(
    client: httpx.AsyncClient,
    make_admin: AdminFactory,
    make_barber: Callable[..., Awaitable[Barber]],
) -> None:
    me = await make_barber("Я")
    other = await make_barber("Другой")
    await login_as(client, await make_admin(AdminRole.BARBER, barber_id=me.id))

    listed = await client.get(f"{API}/barbers")
    assert [item["id"] for item in listed.json()["items"]] == [str(me.id)]
    assert (await client.get(f"{API}/barbers/{me.id}")).status_code == 200
    assert (await client.get(f"{API}/barbers/{other.id}")).status_code == 403

    assert (await client.patch(f"{API}/barbers/{me.id}", json={"name": "Z"})).status_code == 403
    response = await client.post(
        f"{API}/services",
        json={"name_i18n": {"ru": "X"}, "duration_min": 30, "base_price": 1},
    )
    assert response.status_code == 403
    assert (await client.get(f"{API}/services")).status_code == 200


async def test_barber_role_without_link_sees_nothing(
    client: httpx.AsyncClient,
    make_admin: AdminFactory,
    make_barber: Callable[..., Awaitable[Barber]],
) -> None:
    await make_barber()
    await login_as(client, await make_admin(AdminRole.BARBER))
    listed = await client.get(f"{API}/barbers")
    assert listed.json()["items"] == []


async def test_admin_can_manage_catalog(
    client: httpx.AsyncClient, make_admin: AdminFactory
) -> None:
    await login_as(client, await make_admin(AdminRole.ADMIN))
    assert await _service(client, "Стрижка", 30, 1000)
