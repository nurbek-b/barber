from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.api.deps import AdminDep, RedisDep, SessionDep, SettingsDep, client_ip
from app.core.errors import ErrorResponse, RateLimitedError, UnauthorizedError
from app.core.redis import hit_rate_limit
from app.core.security.cookies import clear_session, read_session, set_session
from app.core.security.tokens import WS_TICKET_TTL_SECONDS
from app.models import AdminUser
from app.schemas.auth import (
    AdminMe,
    LoginRequest,
    LoginResponse,
    RefreshResponse,
    WsTicketResponse,
)
from app.services.admin_auth import AdminAuthService
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
    set_session(response, issued, settings)
    return LoginResponse(user=to_me(issued.admin), csrf_token=issued.csrf_token)


@router.post("/refresh", response_model=RefreshResponse, responses=ERRORS)
async def refresh(
    request: Request, response: Response, session: SessionDep, settings: SettingsDep
) -> RefreshResponse:
    """Rotates the refresh token. No CSRF check: the cookie is SameSite=Strict and scoped
    to this path, and the endpoint only reissues the caller's own session."""
    issued = await AdminAuthService(session, settings).refresh(
        read_session(request.cookies, settings).refresh,
        user_agent=request.headers.get("user-agent"),
        ip=client_ip(request),
    )
    set_session(response, issued, settings)
    return RefreshResponse(csrf_token=issued.csrf_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request, response: Response, session: SessionDep, settings: SettingsDep
) -> Response:
    service = AdminAuthService(session, settings)
    claims = None
    tokens = read_session(request.cookies, settings)
    access = tokens.access
    if access:
        try:
            claims = service.decode_access(access)
        except UnauthorizedError:  # expired access token is fine for logout
            claims = None
    await service.logout(tokens.refresh, claims)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session(response, settings)
    return response


@router.get("/me", response_model=AdminMe, responses=ERRORS)
async def me(ctx: AdminDep) -> AdminMe:
    return to_me(ctx.admin)


@router.post("/ws-ticket", response_model=WsTicketResponse, responses=ERRORS)
async def ws_ticket(ctx: AdminDep, session: SessionDep, settings: SettingsDep) -> WsTicketResponse:
    """One-minute ticket for `/admin/ws?ticket=...` when the socket goes to another origin
    (Firebase Hosting cannot proxy WebSockets, so the admin talks to Cloud Run directly)."""
    ticket = AdminAuthService(session, settings).issue_ws_ticket(ctx.claims)
    return WsTicketResponse(ticket=ticket, expires_in=WS_TICKET_TTL_SECONDS)
