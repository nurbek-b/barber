from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.api.deps import AdminDep, RedisDep, SessionDep, SettingsDep, client_ip
from app.core.config import Settings
from app.core.errors import ErrorResponse, RateLimitedError, UnauthorizedError
from app.core.redis import hit_rate_limit
from app.core.security.tokens import (
    ACCESS_COOKIE,
    CSRF_COOKIE,
    REFRESH_COOKIE,
    REFRESH_COOKIE_PATH,
)
from app.models import AdminUser
from app.schemas.auth import AdminMe, LoginRequest, LoginResponse, RefreshResponse
from app.services.admin_auth import AdminAuthService, IssuedSession
from app.services.permissions import permissions_for

router = APIRouter(prefix="/auth", tags=["admin-auth"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
}


def to_me(admin: AdminUser) -> AdminMe:
    return AdminMe(
        id=admin.id,
        login=admin.login,
        full_name=admin.full_name,
        role=admin.role,
        branch_id=admin.branch_id,
        barber_id=admin.barber_id,
        language=admin.language,
        permissions=sorted(perm.value for perm in permissions_for(admin.role)),
    )


def _set_session_cookies(response: Response, issued: IssuedSession, settings: Settings) -> None:
    common = {"secure": settings.cookie_secure, "domain": settings.cookie_domain}
    response.set_cookie(
        ACCESS_COOKIE,
        issued.access_token,
        max_age=settings.access_token_ttl_seconds,
        httponly=True,
        samesite="strict",
        path="/",
        **common,  # type: ignore[arg-type]
    )
    response.set_cookie(
        REFRESH_COOKIE,
        issued.refresh_token,
        max_age=settings.refresh_token_ttl_seconds,
        httponly=True,
        samesite="strict",
        path=REFRESH_COOKIE_PATH,
        **common,  # type: ignore[arg-type]
    )
    # Readable by JS: double-submit CSRF token echoed back in X-CSRF-Token.
    response.set_cookie(
        CSRF_COOKIE,
        issued.csrf_token,
        max_age=settings.refresh_token_ttl_seconds,
        httponly=False,
        samesite="strict",
        path="/",
        **common,  # type: ignore[arg-type]
    )


def _clear_session_cookies(response: Response, settings: Settings) -> None:
    for name, path in (
        (ACCESS_COOKIE, "/"),
        (REFRESH_COOKIE, REFRESH_COOKIE_PATH),
        (CSRF_COOKIE, "/"),
    ):
        response.delete_cookie(name, path=path, domain=settings.cookie_domain)


@router.post("/login", response_model=LoginResponse, responses=ERRORS)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    redis: RedisDep,
) -> LoginResponse:
    ip = client_ip(request) or "unknown"
    key = f"login:{ip}:{body.login.strip().lower()}"
    if await hit_rate_limit(redis, key, settings.login_rate_limit_per_minute, 60):
        raise RateLimitedError("Too many login attempts", headers={"Retry-After": "60"})
    issued = await AdminAuthService(session, settings).login(
        body.login, body.password, user_agent=request.headers.get("user-agent"), ip=ip
    )
    _set_session_cookies(response, issued, settings)
    return LoginResponse(user=to_me(issued.admin), csrf_token=issued.csrf_token)


@router.post("/refresh", response_model=RefreshResponse, responses=ERRORS)
async def refresh(
    request: Request, response: Response, session: SessionDep, settings: SettingsDep
) -> RefreshResponse:
    """Rotates the refresh token. No CSRF check: the cookie is SameSite=Strict and scoped
    to this path, and the endpoint only reissues the caller's own session."""
    issued = await AdminAuthService(session, settings).refresh(
        request.cookies.get(REFRESH_COOKIE),
        user_agent=request.headers.get("user-agent"),
        ip=client_ip(request),
    )
    _set_session_cookies(response, issued, settings)
    return RefreshResponse(csrf_token=issued.csrf_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request, response: Response, session: SessionDep, settings: SettingsDep
) -> Response:
    service = AdminAuthService(session, settings)
    claims = None
    access = request.cookies.get(ACCESS_COOKIE)
    if access:
        try:
            claims = service.decode_access(access)
        except UnauthorizedError:  # expired access token is fine for logout
            claims = None
    await service.logout(request.cookies.get(REFRESH_COOKIE), claims)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_session_cookies(response, settings)
    return response


@router.get("/me", response_model=AdminMe, responses=ERRORS)
async def me(ctx: AdminDep) -> AdminMe:
    return to_me(ctx.admin)
