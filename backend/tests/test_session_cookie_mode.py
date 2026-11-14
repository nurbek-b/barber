"""COOKIE_MODE=session: everything in one `__session` cookie (Firebase Hosting -> Cloud Run)."""

from __future__ import annotations

import asyncio

import pytest
from fakeredis import FakeAsyncRedis
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import Settings
from app.main import create_app
from app.models.enums import AdminRole
from tests.conftest import PASSWORD, AdminFactory

AUTH = "/api/v1/admin/auth"


def _client(settings: Settings) -> TestClient:
    session_mode = settings.model_copy(
        update={
            "cookie_mode": "session",
            "cookie_secure": False,
            "cors_origins": ["https://britva.example"],
        }
    )
    app = create_app(session_mode, redis=FakeAsyncRedis(decode_responses=True))
    return TestClient(app, base_url="https://testserver")


async def test_login_csrf_refresh_logout_with_single_cookie(
    settings: Settings, make_admin: AdminFactory
) -> None:
    owner = await make_admin(AdminRole.OWNER)

    def scenario() -> None:
        with _client(settings) as http:
            login = http.post(f"{AUTH}/login", json={"login": owner.login, "password": PASSWORD})
            assert login.status_code == 200, login.text
            assert set(http.cookies.keys()) == {"__session"}
            set_cookie = login.headers["set-cookie"].lower()
            assert "httponly" in set_cookie
            assert "samesite=strict" in set_cookie
            csrf = login.json()["csrf_token"]
            assert csrf in http.cookies["__session"]

            assert http.get(f"{AUTH}/me").status_code == 200
            # state-changing request without / with a wrong / with the right header
            assert http.post(f"{AUTH}/ws-ticket").status_code == 403
            bad = http.post(f"{AUTH}/ws-ticket", headers={"X-CSRF-Token": "nope"})
            assert bad.status_code == 403
            ok = http.post(f"{AUTH}/ws-ticket", headers={"X-CSRF-Token": csrf})
            assert ok.status_code == 200
            assert ok.json()["expires_in"] == 60

            old_cookie = http.cookies["__session"]
            refreshed = http.post(f"{AUTH}/refresh")
            assert refreshed.status_code == 200, refreshed.text
            new_csrf = refreshed.json()["csrf_token"]
            assert new_csrf != csrf
            assert http.cookies["__session"] != old_cookie
            assert http.post(f"{AUTH}/ws-ticket", headers={"X-CSRF-Token": csrf}).status_code == 403
            assert (
                http.post(f"{AUTH}/ws-ticket", headers={"X-CSRF-Token": new_csrf}).status_code
                == 200
            )

            # the rotated-away refresh token is dead (reuse detection revokes the family)
            http.cookies.clear()
            http.cookies.set("__session", old_cookie)
            stale = http.post(f"{AUTH}/refresh")
            assert stale.status_code == 401

            http.cookies.clear()
            assert http.get(f"{AUTH}/me").status_code == 401

    await asyncio.to_thread(scenario)


async def test_logout_clears_session_cookie(settings: Settings, make_admin: AdminFactory) -> None:
    owner = await make_admin(AdminRole.OWNER)

    def scenario() -> None:
        with _client(settings) as http:
            login = http.post(f"{AUTH}/login", json={"login": owner.login, "password": PASSWORD})
            csrf = login.json()["csrf_token"]
            out = http.post(f"{AUTH}/logout", headers={"X-CSRF-Token": csrf})
            assert out.status_code == 204
            assert "__session" not in http.cookies
            assert http.get(f"{AUTH}/me").status_code == 401

    await asyncio.to_thread(scenario)


async def test_websocket_ticket_from_other_origin(
    settings: Settings, make_admin: AdminFactory
) -> None:
    owner = await make_admin(AdminRole.OWNER)

    def scenario() -> tuple[str, list[int]]:
        with _client(settings) as http:
            login = http.post(f"{AUTH}/login", json={"login": owner.login, "password": PASSWORD})
            csrf = login.json()["csrf_token"]
            ticket = http.post(f"{AUTH}/ws-ticket", headers={"X-CSRF-Token": csrf}).json()["ticket"]
            http.cookies.clear()  # Cloud Run origin: no cookie, only the ticket
            origin = {"origin": "https://britva.example"}
            with http.websocket_connect(f"/api/v1/admin/ws?ticket={ticket}", headers=origin) as ws:
                hello = ws.receive_json()["type"]
            codes = []
            for url, headers in (
                ("/api/v1/admin/ws?ticket=garbage", origin),
                (f"/api/v1/admin/ws?ticket={ticket}", {"origin": "https://evil.example"}),
            ):
                with (
                    pytest.raises(WebSocketDisconnect) as exc_info,
                    http.websocket_connect(url, headers=headers) as ws,
                ):
                    ws.receive_json()
                codes.append(exc_info.value.code)
            return hello, codes

    hello, codes = await asyncio.to_thread(scenario)
    assert hello == "hello"
    assert codes == [1008, 1008]
