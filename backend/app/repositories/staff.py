from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdminRefreshToken, AdminUser


class AdminUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, admin_user_id: uuid.UUID) -> AdminUser | None:
        return await self.session.get(AdminUser, admin_user_id)

    async def get_by_login(self, login: str) -> AdminUser | None:
        result = await self.session.execute(
            select(AdminUser).where(AdminUser.login == login.strip().lower())
        )
        return result.scalar_one_or_none()

    def add(self, admin: AdminUser) -> None:
        self.session.add(admin)


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, token: AdminRefreshToken) -> None:
        self.session.add(token)

    async def get_by_hash_for_update(self, token_hash: str) -> AdminRefreshToken | None:
        result = await self.session.execute(
            select(AdminRefreshToken)
            .where(AdminRefreshToken.token_hash == token_hash)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def revoke_family(self, family_id: uuid.UUID, now: datetime) -> None:
        await self.session.execute(
            update(AdminRefreshToken)
            .where(
                AdminRefreshToken.family_id == family_id,
                AdminRefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

    async def is_family_active(self, family_id: uuid.UUID, now: datetime) -> bool:
        result = await self.session.execute(
            select(AdminRefreshToken.id)
            .where(
                AdminRefreshToken.family_id == family_id,
                AdminRefreshToken.revoked_at.is_(None),
                AdminRefreshToken.expires_at > now,
            )
            .limit(1)
        )
        return result.first() is not None
