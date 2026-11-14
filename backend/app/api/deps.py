from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import session_scope
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security.cookies import read_session
from app.core.security.tokens import CSRF_HEADER, AccessClaims, csrf_matches
from app.models import AdminUser
from app.models.enums import ActorType, AdminRole
from app.services.admin_auth import AdminAuthService
from app.services.audit import Actor
from app.services.branches import BranchService
from app.services.miniapp_auth import MiniappAuthService, MiniappIdentity
from app.services.permissions import Perm, has_permission
from app.services.slot_cache import SlotCache

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async for session in session_scope(request.app.state.sessionmaker):
        yield session


def get_redis(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis


def get_now() -> datetime:
    """Current instant. Overridden in tests via app.dependency_overrides."""
    return datetime.now(UTC)


def get_slot_cache(request: Request) -> SlotCache:
    return SlotCache(request.app.state.redis)


NowDep = Annotated[datetime, Depends(get_now)]
SlotCacheDep = Annotated[SlotCache, Depends(get_slot_cache)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]


def client_ip(request: Request) -> str | None:
    # Nginx sets X-Real-IP; uvicorn runs with --proxy-headers behind it.
    return request.headers.get("x-real-ip") or (request.client.host if request.client else None)


# ---------------- admin ----------------


@dataclass(slots=True)
class AdminContext:
    admin: AdminUser
    claims: AccessClaims
    branch_id: uuid.UUID
    actor: Actor

    @property
    def role(self) -> AdminRole:
        return self.admin.role

    def can(self, perm: Perm) -> bool:
        return has_permission(self.admin.role, perm)


async def get_admin_context(
    request: Request, session: SessionDep, settings: SettingsDep
) -> AdminContext:
    service = AdminAuthService(session, settings)
    tokens = read_session(request.cookies, settings)
    admin, claims = await service.authenticate_access(tokens.access)
    if request.method not in SAFE_METHODS and not csrf_matches(
        tokens.csrf, request.headers.get(CSRF_HEADER)
    ):
        raise ForbiddenError("CSRF token is missing or invalid", code="csrf_failed")
    branch_id = await BranchService(session).branch_for_admin(admin)
    actor = Actor(
        type=ActorType.ADMIN,
        id=admin.id,
        ip=client_ip(request),
        request_id=getattr(request.state, "request_id", None),
    )
    return AdminContext(admin=admin, claims=claims, branch_id=branch_id, actor=actor)


AdminDep = Annotated[AdminContext, Depends(get_admin_context)]


def require(*perms: Perm) -> Callable[..., Coroutine[Any, Any, AdminContext]]:
    """Dependency: the admin must have at least one of `perms`."""

    async def dependency(ctx: AdminDep) -> AdminContext:
        if not any(ctx.can(perm) for perm in perms):
            raise ForbiddenError()
        return ctx

    return dependency


def ensure_own_barber(ctx: AdminContext, barber_id: uuid.UUID, full: Perm) -> None:
    """For barber-role accounts: allow access only to their own barber record."""
    if ctx.can(full):
        return
    if ctx.admin.barber_id is None or ctx.admin.barber_id != barber_id:
        raise ForbiddenError()


# ---------------- mini app ----------------


@dataclass(slots=True)
class MiniappContext:
    identity: MiniappIdentity
    branch_id: uuid.UUID

    @property
    def client_id(self) -> uuid.UUID:
        return self.identity.client.id

    @property
    def actor(self) -> Actor:
        return self.identity.actor


async def get_miniapp_context(
    session: SessionDep,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> MiniappContext:
    if authorization is None:
        raise UnauthorizedError("Authorization header is missing")
    branches = BranchService(session)
    branch_id = await branches.default_branch_id()
    salon = await branches.settings(branch_id)
    identity = await MiniappAuthService(session, settings).authenticate(
        authorization, branch_id, salon.default_language
    )
    return MiniappContext(identity=identity, branch_id=branch_id)


MiniappDep = Annotated[MiniappContext, Depends(get_miniapp_context)]
