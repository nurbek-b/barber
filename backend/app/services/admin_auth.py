from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security.passwords import hash_password, needs_rehash, verify_password
from app.core.security.tokens import (
    AccessClaims,
    TokenError,
    create_access_token,
    create_ws_ticket,
    decode_access_token,
    decode_ws_ticket,
    hash_token,
    new_csrf_token,
    new_refresh_token,
)
from app.models import AdminRefreshToken, AdminUser
from app.models.enums import ActorType
from app.repositories.staff import AdminUserRepository, RefreshTokenRepository
from app.services.audit import Actor, AuditService

# Two tabs refreshing at the same moment both present the same token. Within this window the
# second request gets 401 without revoking the session; outside it, reuse means token theft.
REFRESH_REUSE_GRACE = timedelta(seconds=15)


@dataclass(frozen=True, slots=True)
class IssuedSession:
    admin: AdminUser
    access_token: str
    refresh_token: str
    csrf_token: str


class AdminAuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.admins = AdminUserRepository(session)
        self.tokens = RefreshTokenRepository(session)
        self.audit = AuditService(session)

    def _jwt_secret(self) -> str:
        secret = self.settings.jwt_secret.get_secret_value()
        if not secret:
            raise RuntimeError("JWT_SECRET is not configured")
        return secret

    async def _issue(
        self,
        admin: AdminUser,
        family_id: uuid.UUID,
        now: datetime,
        user_agent: str | None,
        ip: str | None,
    ) -> IssuedSession:
        refresh = new_refresh_token()
        self.tokens.add(
            AdminRefreshToken(
                admin_user_id=admin.id,
                family_id=family_id,
                token_hash=hash_token(refresh),
                created_at=now,
                expires_at=now + timedelta(seconds=self.settings.refresh_token_ttl_seconds),
                user_agent=(user_agent or "")[:255] or None,
                ip=ip,
            )
        )
        access = create_access_token(
            admin_user_id=admin.id,
            role=admin.role.value,
            session_family=family_id,
            secret=self._jwt_secret(),
            algorithm=self.settings.jwt_algorithm,
            ttl_seconds=self.settings.access_token_ttl_seconds,
            now=now,
        )
        return IssuedSession(
            admin=admin, access_token=access, refresh_token=refresh, csrf_token=new_csrf_token()
        )

    async def login(
        self, login: str, password: str, *, user_agent: str | None, ip: str | None
    ) -> IssuedSession:
        admin = await self.admins.get_by_login(login)
        valid = verify_password(admin.password_hash if admin else None, password)
        if admin is None or not valid:
            raise UnauthorizedError("Invalid login or password", code="invalid_credentials")
        if not admin.is_active:
            raise ForbiddenError("Account is disabled", code="account_disabled")

        now = datetime.now(UTC)
        if needs_rehash(admin.password_hash):
            admin.password_hash = hash_password(password)
        admin.last_login_at = now
        issued = await self._issue(admin, uuid.uuid4(), now, user_agent, ip)
        self.audit.record(
            Actor(type=ActorType.ADMIN, id=admin.id, ip=ip), "auth.login", "admin_user", admin.id
        )
        await self.session.commit()
        return issued

    async def refresh(
        self, refresh_token: str | None, *, user_agent: str | None, ip: str | None
    ) -> IssuedSession:
        if not refresh_token:
            raise UnauthorizedError("Refresh token is missing", code="refresh_missing")
        now = datetime.now(UTC)
        stored = await self.tokens.get_by_hash_for_update(hash_token(refresh_token))
        if stored is None:
            raise UnauthorizedError("Invalid refresh token", code="refresh_invalid")

        if stored.revoked_at is not None or stored.expires_at <= now:
            raise UnauthorizedError("Session expired", code="refresh_invalid")

        if stored.used_at is not None:
            if now - stored.used_at <= REFRESH_REUSE_GRACE:
                raise UnauthorizedError("Refresh already in progress", code="refresh_race")
            # Reuse of a rotated token: assume it was stolen, kill the whole session family.
            await self.tokens.revoke_family(stored.family_id, now)
            await self.session.commit()
            raise UnauthorizedError("Session revoked", code="refresh_reused")

        admin = await self.admins.get(stored.admin_user_id)
        if admin is None or not admin.is_active:
            await self.tokens.revoke_family(stored.family_id, now)
            await self.session.commit()
            raise UnauthorizedError("Account is disabled", code="account_disabled")

        stored.used_at = now
        issued = await self._issue(admin, stored.family_id, now, user_agent, ip)
        await self.session.commit()
        return issued

    async def logout(self, refresh_token: str | None, claims: AccessClaims | None) -> None:
        now = datetime.now(UTC)
        family: uuid.UUID | None = claims.session_family if claims else None
        if family is None and refresh_token:
            stored = await self.tokens.get_by_hash_for_update(hash_token(refresh_token))
            family = stored.family_id if stored else None
        if family is not None:
            await self.tokens.revoke_family(family, now)
            await self.session.commit()

    def decode_access(self, token: str) -> AccessClaims:
        try:
            return decode_access_token(
                token, secret=self._jwt_secret(), algorithm=self.settings.jwt_algorithm
            )
        except TokenError as exc:
            raise UnauthorizedError(
                "Invalid or expired access token", code="token_invalid"
            ) from exc

    async def authenticate_access(self, token: str | None) -> tuple[AdminUser, AccessClaims]:
        if not token:
            raise UnauthorizedError()
        return await self._authenticate_claims(self.decode_access(token))

    def issue_ws_ticket(self, claims: AccessClaims) -> str:
        return create_ws_ticket(
            claims, secret=self._jwt_secret(), algorithm=self.settings.jwt_algorithm
        )

    async def authenticate_ws_ticket(self, ticket: str | None) -> tuple[AdminUser, AccessClaims]:
        if not ticket:
            raise UnauthorizedError()
        try:
            claims = decode_ws_ticket(
                ticket, secret=self._jwt_secret(), algorithm=self.settings.jwt_algorithm
            )
        except TokenError as exc:
            raise UnauthorizedError("Invalid or expired ticket", code="token_invalid") from exc
        return await self._authenticate_claims(claims)

    async def _authenticate_claims(self, claims: AccessClaims) -> tuple[AdminUser, AccessClaims]:
        admin = await self.admins.get(claims.admin_user_id)
        if admin is None or not admin.is_active:
            raise UnauthorizedError("Account is disabled", code="account_disabled")
        if admin.role.value != claims.role:
            # Role changed after the token was issued: force a refresh with the new role.
            raise UnauthorizedError("Role changed", code="token_invalid")
        return admin, claims
