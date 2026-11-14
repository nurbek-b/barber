from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Branch, SalonSettings


class BranchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_default(self) -> Branch | None:
        result = await self.session.execute(
            select(Branch)
            .where(Branch.is_active.is_(True))
            .order_by(Branch.is_default.desc(), Branch.created_at)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get(self, branch_id: uuid.UUID) -> Branch | None:
        return await self.session.get(Branch, branch_id)

    async def get_settings(self, branch_id: uuid.UUID) -> SalonSettings | None:
        return await self.session.get(SalonSettings, branch_id)
