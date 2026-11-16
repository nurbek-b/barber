"""Reviews (one per completed visit), public feed, moderation; barber works catalogue."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import Barber, BarberSchedule, Booking, BookingService, Branch, Client
from app.models.enums import AdminRole, BookingStatus
from app.services.reviews import public_author
from tests.conftest import AdminFactory, login_as, tma_header

MINI = "/api/v1/miniapp"
ADMIN = "/api/v1/admin"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def test_public_author() -> None:
    assert public_author("Бектур Асанов") == "Бектур А."
    assert public_author("Бек") == "Бек"
    assert public_author("  ") == ""


async def _client(http: httpx.AsyncClient, session: AsyncSession, tg_id: int, name: str) -> Client:
    me = await http.get(f"{MINI}/me", headers=tma_header(tg_id, first_name=name))
    assert me.status_code == 200, me.text
    client = await session.get(Client, me.json()["id"])
    assert client is not None
    client.name = f"{name} Асанов"
    await session.commit()
    return client


async def _visit(
    session: AsyncSession, branch: Branch, client: Client, barber: Barber, days_ago: float
) -> Booking:
    end = datetime.now(UTC) - timedelta(days=days_ago)
    booking = Booking(
        branch_id=branch.id,
        client_id=client.id,
        barber_id=barber.id,
        status=BookingStatus.COMPLETED,
        start_at=end - timedelta(hours=1),
        end_at=end,
        blocked_until=end,
        subtotal=100_000,
        bonus_spent=0,
        total_due=100_000,
        completed_at=end,
        services=[BookingService(name_snapshot={"ru": "Стрижка"}, duration_min=60, price=100_000)],
    )
    session.add(booking)
    await session.commit()
    return booking


async def _barber(session: AsyncSession, branch: Branch) -> Barber:
    barber = Barber(branch_id=branch.id, name="Азамат")
    session.add(barber)
    await session.flush()
    session.add(BarberSchedule(barber_id=barber.id, weekday=0, start_time=_t(10), end_time=_t(18)))
    await session.commit()
    return barber


def _t(hour: int) -> time:
    return time(hour)


async def test_review_lifecycle(
    client: httpx.AsyncClient,
    session: AsyncSession,
    branch: Branch,
    make_admin: AdminFactory,
) -> None:
    barber = await _barber(session, branch)
    alice = await _client(client, session, 9001, "Айгуль")
    bob = await _client(client, session, 9002, "Бакыт")
    visit = await _visit(session, branch, alice, barber, days_ago=2)
    old = await _visit(session, branch, alice, barber, days_ago=40)
    headers = tma_header(9001, first_name="Айгуль")

    listed = (
        await client.get(f"{MINI}/bookings", headers=headers, params={"scope": "past"})
    ).json()
    flags = {item["id"]: item["can_review"] for item in listed["items"]}
    assert flags == {str(visit.id): True, str(old.id): False}

    url = f"{MINI}/bookings/{visit.id}/review"
    created = await client.put(url, headers=headers, json={"rating": 4, "text": "  Отлично!  "})
    assert created.status_code == 200, created.text
    assert created.json()["rating"] == 4
    assert created.json()["review_text"] == "Отлично!"
    edited = await client.put(url, headers=headers, json={"rating": 5, "text": "Лучший"})
    assert edited.json()["rating"] == 5

    # someone else's visit, too old, invalid rating
    foreign = await client.put(
        url, headers=tma_header(9002, first_name="Бакыт"), json={"rating": 1}
    )
    assert foreign.status_code == 404
    too_old = await client.put(
        f"{MINI}/bookings/{old.id}/review", headers=headers, json={"rating": 5}
    )
    assert too_old.status_code == 422
    assert too_old.json()["error"]["code"] == "review_unavailable"
    assert (await client.put(url, headers=headers, json={"rating": 6})).status_code == 422

    bob_visit = await _visit(session, branch, bob, barber, days_ago=1)
    await client.put(
        f"{MINI}/bookings/{bob_visit.id}/review",
        headers=tma_header(9002, first_name="Бакыт"),
        json={"rating": 2},
    )

    profile = (await client.get(f"{MINI}/barbers/{barber.id}", headers=headers)).json()
    assert profile["rating"] == 3.5
    assert profile["rating_count"] == 2

    page1 = (
        await client.get(
            f"{MINI}/barbers/{barber.id}/reviews", headers=headers, params={"limit": 1}
        )
    ).json()
    assert [item["author"] for item in page1["items"]] == ["Бакыт А."]  # newest first
    assert page1["items"][0]["text"] is None
    page2 = (
        await client.get(
            f"{MINI}/barbers/{barber.id}/reviews",
            headers=headers,
            params={"limit": 1, "cursor": page1["next_cursor"]},
        )
    ).json()
    assert [item["author"] for item in page2["items"]] == ["Айгуль А."]
    assert page2["items"][0]["services"] == [{"ru": "Стрижка"}]
    assert page2["next_cursor"] is None

    # moderation: hiding removes the review from the feed and from the average
    await login_as(client, await make_admin(AdminRole.ADMIN))
    admin_list = (await client.get(f"{ADMIN}/reviews", params={"barber_id": str(barber.id)})).json()
    assert admin_list["total"] == 2
    assert {item["client_name"] for item in admin_list["items"]} == {
        "Айгуль Асанов",
        "Бакыт Асанов",
    }
    hidden = await client.post(f"{ADMIN}/reviews/{bob_visit.id}/visibility", json={"hidden": True})
    assert hidden.status_code == 200
    assert hidden.json()["hidden"] is True
    profile = (await client.get(f"{MINI}/barbers/{barber.id}", headers=headers)).json()
    assert (profile["rating"], profile["rating_count"]) == (5.0, 1)
    feed = (await client.get(f"{MINI}/barbers/{barber.id}/reviews", headers=headers)).json()
    assert len(feed["items"]) == 1
    only_hidden = (await client.get(f"{ADMIN}/reviews", params={"hidden": True})).json()
    assert only_hidden["total"] == 1


async def test_barber_role_cannot_moderate(
    client: httpx.AsyncClient, make_admin: AdminFactory
) -> None:
    await login_as(client, await make_admin(AdminRole.BARBER))
    assert (await client.get(f"{ADMIN}/reviews")).status_code == 403


async def test_portfolio(
    owner_client: httpx.AsyncClient,
    client: httpx.AsyncClient,
    session: AsyncSession,
    branch: Branch,
    settings: Settings,
) -> None:
    barber = await _barber(session, branch)
    url = f"{ADMIN}/barbers/{barber.id}/portfolio"
    urls: list[str] = []
    for name in ("a.png", "b.png"):
        response = await owner_client.post(url, files={"file": (name, PNG, "image/png")})
        assert response.status_code == 200, response.text
        urls = response.json()["portfolio"]
    assert len(urls) == 2
    assert all(item.startswith("/media/portfolio/") for item in urls)

    reordered = await owner_client.put(url, json={"urls": [urls[1]]})
    assert reordered.json()["portfolio"] == [urls[1]]
    assert not (Path(settings.media_dir) / urls[0].removeprefix("/media/")).exists()

    profile = await client.get(f"{MINI}/barbers/{barber.id}", headers=tma_header())
    assert profile.json()["portfolio"] == [urls[1]]

    barber.is_bookable_online = False
    await session.commit()
    hidden = await client.get(f"{MINI}/barbers/{barber.id}", headers=tma_header())
    assert hidden.status_code == 404


async def test_map_review_links(owner_client: httpx.AsyncClient) -> None:
    current = (await owner_client.get(f"{ADMIN}/settings/salon")).json()
    assert current["review_links"] == {}
    links = {"2gis": " https://2gis.kg/bishkek/firm/1 ", "google": ""}
    saved = await owner_client.put(
        f"{ADMIN}/settings/salon", json={**current, "review_links": links}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["review_links"] == {"2gis": "https://2gis.kg/bishkek/firm/1"}
    for bad in ({"yandex": "https://ya.ru"}, {"google": "http://maps.google.com"}):
        response = await owner_client.put(
            f"{ADMIN}/settings/salon", json={**current, "review_links": bad}
        )
        assert response.status_code == 422

    salon = await owner_client.get(f"{MINI}/salon", headers=tma_header(31, first_name="Map"))
    assert salon.json()["review_links"] == {"2gis": "https://2gis.kg/bishkek/firm/1"}


def test_review_keyboard_map_buttons(settings: Settings) -> None:
    from app.bot.keyboards import write_review

    plain = write_review(settings, "ru", "b1")
    assert len(plain.inline_keyboard) == 1
    happy = write_review(settings, "en", "b1", {"google": "https://g.co/x", "2gis": "https://2gis"})
    urls = [row[0].url for row in happy.inline_keyboard[:2]]
    assert urls == ["https://2gis", "https://g.co/x"]
    assert happy.inline_keyboard[0][0].text == "⭐ Review on 2GIS"
