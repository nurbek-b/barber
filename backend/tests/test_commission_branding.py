"""Barber commission (owner only, fixed at completion), schedule flag, photo removal, branding."""

from __future__ import annotations

from datetime import time
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import Barber, BarberSchedule, Booking, Branch
from app.models.enums import AdminRole
from app.services.reports import master_share
from tests.conftest import AdminFactory, login_as, tma_header
from tests.test_admin_extra import _finance_world, clock  # noqa: F401 - pytest fixture

ADMIN = "/api/v1/admin"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def test_master_share_rounding() -> None:
    assert master_share(100_000, 4_000) == 40_000
    assert master_share(333, 5_000) == 167  # 166.5 tyiyn -> half up
    assert master_share(100_000, 0) == 0
    assert master_share(100_000, 10_000) == 100_000


@pytest.mark.usefixtures("clock")
async def test_commission_in_finance_report(
    owner_client: httpx.AsyncClient, session: AsyncSession, branch: Branch
) -> None:
    first, second = await _finance_world(session, branch)
    patched = await owner_client.patch(f"{ADMIN}/barbers/{first.id}", json={"commission_bp": 4000})
    assert patched.status_code == 200, patched.text
    assert patched.json()["commission_bp"] == 4000
    await owner_client.patch(f"{ADMIN}/barbers/{second.id}", json={"commission_bp": 5000})

    # one of the first barber's visits was completed when his rate was 50 %
    booking = (
        await session.execute(
            select(Booking).where(Booking.barber_id == first.id, Booking.subtotal == 50_000)
        )
    ).scalar_one()
    booking.barber_commission_bp = 5000
    await session.commit()

    params = {"date_from": "2026-12-01", "date_to": "2026-12-07"}
    report = (await owner_client.get(f"{ADMIN}/finance/report", params=params)).json()
    rows = {item["name"]: item for item in report["by_barber"]}
    # first: 100 000 and 70 000 at 40 %, 50 000 at the fixed 50 %
    assert rows["Первый"]["master_share"] == 40_000 + 28_000 + 25_000
    assert rows["Первый"]["commission_bp"] == 4000
    assert rows["Второй"]["master_share"] == 50_000
    assert report["totals"]["master_share"] == 143_000


async def test_only_owner_sets_commission(
    client: httpx.AsyncClient, make_admin: AdminFactory, session: AsyncSession, branch: Branch
) -> None:
    barber = Barber(branch_id=branch.id, name="Азамат")
    session.add(barber)
    await session.commit()
    await login_as(client, await make_admin(AdminRole.ADMIN))
    denied = await client.patch(f"{ADMIN}/barbers/{barber.id}", json={"commission_bp": 3000})
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "owner_only"
    renamed = await client.patch(f"{ADMIN}/barbers/{barber.id}", json={"name": "Азамат Б."})
    assert renamed.status_code == 200
    created = await client.post(f"{ADMIN}/barbers", json={"name": "Новый", "commission_bp": 1})
    assert created.status_code == 403
    too_much = await client.post(f"{ADMIN}/barbers", json={"name": "Новый", "commission_bp": 10001})
    assert too_much.status_code == 422


async def test_schedule_flag_and_public_list(
    owner_client: httpx.AsyncClient, client: httpx.AsyncClient, session: AsyncSession
) -> None:
    created = (await owner_client.post(f"{ADMIN}/barbers", json={"name": "Без графика"})).json()
    assert created["has_schedule"] is False
    listed = (await owner_client.get(f"{ADMIN}/barbers")).json()["items"]
    assert [item["has_schedule"] for item in listed] == [False]
    public = await client.get("/api/v1/miniapp/barbers", headers=tma_header())
    assert public.json() == [], "a barber without hours cannot be booked"

    session.add(
        BarberSchedule(barber_id=created["id"], weekday=0, start_time=time(10), end_time=time(18))
    )
    await session.commit()
    detail = (await owner_client.get(f"{ADMIN}/barbers/{created['id']}")).json()
    assert detail["has_schedule"] is True
    public = await client.get("/api/v1/miniapp/barbers", headers=tma_header())
    assert [item["name"] for item in public.json()] == ["Без графика"]


async def test_remove_photo(owner_client: httpx.AsyncClient, settings: Settings) -> None:
    barber = (await owner_client.post(f"{ADMIN}/barbers", json={"name": "Фото"})).json()
    url = f"{ADMIN}/barbers/{barber['id']}/photo"
    photo = (await owner_client.post(url, files={"file": ("a.png", PNG, "image/png")})).json()
    path = Path(settings.media_dir) / photo["photo_url"].removeprefix("/media/")
    assert path.exists()
    removed = await owner_client.delete(url)
    assert removed.status_code == 200
    assert removed.json()["photo_url"] is None
    assert not path.exists()


async def test_salon_logo_and_gallery(
    owner_client: httpx.AsyncClient, client: httpx.AsyncClient, settings: Settings
) -> None:
    files = {"file": ("logo.png", PNG, "image/png")}
    logo = await owner_client.post(f"{ADMIN}/settings/salon/logo", files=files)
    assert logo.status_code == 200, logo.text
    logo_url = logo.json()["logo_url"]
    assert logo_url.startswith("/media/salon/")

    urls = []
    for name in ("a.png", "b.png", "c.png"):
        added = await owner_client.post(
            f"{ADMIN}/settings/salon/gallery", files={"file": (name, PNG, "image/png")}
        )
        assert added.status_code == 200
        urls = added.json()["gallery"]
    assert len(urls) == 3

    # reorder and drop the first photo: its file is deleted
    reordered = await owner_client.put(
        f"{ADMIN}/settings/salon/gallery", json={"urls": [urls[2], urls[1]]}
    )
    assert reordered.json()["gallery"] == [urls[2], urls[1]]
    assert not (Path(settings.media_dir) / urls[0].removeprefix("/media/")).exists()
    bad = await owner_client.put(f"{ADMIN}/settings/salon/gallery", json={"urls": ["/media/x"]})
    assert bad.status_code == 422

    salon = (await client.get("/api/v1/miniapp/salon", headers=tma_header())).json()
    assert salon["logo_url"] == logo_url
    assert salon["gallery"] == [urls[2], urls[1]]

    cleared = await owner_client.delete(f"{ADMIN}/settings/salon/logo")
    assert cleared.json()["logo_url"] is None
    assert not (Path(settings.media_dir) / logo_url.removeprefix("/media/")).exists()


async def test_gallery_limit(owner_client: httpx.AsyncClient) -> None:
    for _ in range(8):
        await owner_client.post(
            f"{ADMIN}/settings/salon/gallery", files={"file": ("a.png", PNG, "image/png")}
        )
    full = await owner_client.post(
        f"{ADMIN}/settings/salon/gallery", files={"file": ("a.png", PNG, "image/png")}
    )
    assert full.status_code == 422
    assert full.json()["error"]["code"] == "gallery_full"
