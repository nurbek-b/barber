from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.tokens import ACCESS_COOKIE, CSRF_COOKIE, CSRF_HEADER, REFRESH_COOKIE
from app.models import AdminRefreshToken, AuditLog
from app.models.enums import AdminRole
from tests.conftest import PASSWORD, AdminFactory, login_as

LOGIN = "/api/v1/admin/auth/login"
REFRESH = "/api/v1/admin/auth/refresh"
ME = "/api/v1/admin/auth/me"
LOGOUT = "/api/v1/admin/auth/logout"


async def test_login_sets_httponly_cookies(
    client: httpx.AsyncClient, make_admin: AdminFactory, session: AsyncSession
) -> None:
    admin = await make_admin(AdminRole.ADMIN, login="Manager")
    response = await client.post(LOGIN, json={"login": "  manager ", "password": PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["role"] == "admin"
    assert "finance:read" in body["user"]["permissions"]
    assert "bonus_settings:write" not in body["user"]["permissions"]

    cookies = {c.split("=")[0]: c for c in response.headers.get_list("set-cookie")}
    assert "HttpOnly" in cookies[ACCESS_COOKIE]
    assert "Secure" in cookies[ACCESS_COOKIE]
    assert "SameSite=strict" in cookies[ACCESS_COOKIE]
    assert "Path=/api/v1/admin/auth" in cookies[REFRESH_COOKIE]
    assert "HttpOnly" not in cookies[CSRF_COOKIE]
    assert body["csrf_token"] == client.cookies[CSRF_COOKIE]

    me = await client.get(ME)
    assert me.status_code == 200
    assert me.json()["id"] == str(admin.id)

    audit = await session.scalar(select(AuditLog).where(AuditLog.action == "auth.login"))
    assert audit is not None
    assert audit.actor_id == admin.id


async def test_wrong_password_uses_unified_error(
    client: httpx.AsyncClient, make_admin: AdminFactory
) -> None:
    admin = await make_admin()
    response = await client.post(LOGIN, json={"login": admin.login, "password": "nope"})
    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "invalid_credentials"
    assert error["request_id"]
    assert response.headers["x-request-id"] == error["request_id"]


async def test_unknown_login(client: httpx.AsyncClient, branch: object) -> None:
    response = await client.post(LOGIN, json={"login": "ghost", "password": "whatever"})
    assert response.status_code == 401


async def test_disabled_account(
    client: httpx.AsyncClient, make_admin: AdminFactory, session: AsyncSession
) -> None:
    admin = await make_admin()
    admin.is_active = False
    await session.commit()
    response = await client.post(LOGIN, json={"login": admin.login, "password": PASSWORD})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "account_disabled"


async def test_login_rate_limit(client: httpx.AsyncClient, make_admin: AdminFactory) -> None:
    admin = await make_admin()
    statuses = [
        (await client.post(LOGIN, json={"login": admin.login, "password": "bad"})).status_code
        for _ in range(6)
    ]
    assert statuses[:5] == [401] * 5
    assert statuses[5] == 429


async def test_me_requires_auth(client: httpx.AsyncClient) -> None:
    response = await client.get(ME)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_mutation_requires_csrf(client: httpx.AsyncClient, make_admin: AdminFactory) -> None:
    await login_as(client, await make_admin())
    payload = {"name_i18n": {"ru": "Стрижки"}}

    del client.headers[CSRF_HEADER]
    response = await client.post("/api/v1/admin/service-categories", json=payload)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"

    client.headers[CSRF_HEADER] = "forged"
    response = await client.post("/api/v1/admin/service-categories", json=payload)
    assert response.status_code == 403

    client.headers[CSRF_HEADER] = client.cookies[CSRF_COOKIE]
    response = await client.post("/api/v1/admin/service-categories", json=payload)
    assert response.status_code == 201


async def test_refresh_rotates_token(
    client: httpx.AsyncClient, make_admin: AdminFactory, session: AsyncSession
) -> None:
    await login_as(client, await make_admin())
    first_refresh = client.cookies[REFRESH_COOKIE]

    response = await client.post(REFRESH)
    assert response.status_code == 200
    assert client.cookies[REFRESH_COOKIE] != first_refresh
    assert (await client.get(ME)).status_code == 200

    tokens = (await session.execute(select(AdminRefreshToken))).scalars().all()
    assert len(tokens) == 2
    assert len({token.family_id for token in tokens}) == 1


async def test_refresh_reuse_within_grace_does_not_revoke(
    client: httpx.AsyncClient, make_admin: AdminFactory
) -> None:
    await login_as(client, await make_admin())
    old = client.cookies[REFRESH_COOKIE]
    assert (await client.post(REFRESH)).status_code == 200
    new = client.cookies[REFRESH_COOKIE]

    client.cookies.set(REFRESH_COOKIE, old, path="/api/v1/admin/auth")
    response = await client.post(REFRESH)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "refresh_race"

    client.cookies.set(REFRESH_COOKIE, new, path="/api/v1/admin/auth")
    assert (await client.post(REFRESH)).status_code == 200


async def test_refresh_reuse_after_grace_revokes_family(
    client: httpx.AsyncClient, make_admin: AdminFactory, session: AsyncSession
) -> None:
    await login_as(client, await make_admin())
    stolen = client.cookies[REFRESH_COOKIE]
    assert (await client.post(REFRESH)).status_code == 200
    legit = client.cookies[REFRESH_COOKIE]

    await session.execute(
        update(AdminRefreshToken)
        .where(AdminRefreshToken.used_at.is_not(None))
        .values(used_at=datetime.now(UTC) - timedelta(minutes=5))
    )
    await session.commit()

    client.cookies.set(REFRESH_COOKIE, stolen, path="/api/v1/admin/auth")
    response = await client.post(REFRESH)
    assert response.json()["error"]["code"] == "refresh_reused"

    client.cookies.set(REFRESH_COOKIE, legit, path="/api/v1/admin/auth")
    response = await client.post(REFRESH)
    assert response.status_code == 401


async def test_logout_revokes_session(client: httpx.AsyncClient, make_admin: AdminFactory) -> None:
    await login_as(client, await make_admin())
    refresh = client.cookies[REFRESH_COOKIE]
    assert (await client.post(LOGOUT)).status_code == 204

    client.cookies.set(REFRESH_COOKIE, refresh, path="/api/v1/admin/auth")
    assert (await client.post(REFRESH)).status_code == 401


async def test_role_change_invalidates_access_token(
    client: httpx.AsyncClient, make_admin: AdminFactory, session: AsyncSession
) -> None:
    admin = await make_admin(AdminRole.ADMIN)
    await login_as(client, admin)
    admin.role = AdminRole.BARBER
    await session.commit()
    assert (await client.get(ME)).status_code == 401
    # refresh issues a token with the new role
    assert (await client.post(REFRESH)).status_code == 200
    me = await client.get(ME)
    assert me.json()["role"] == "barber"
