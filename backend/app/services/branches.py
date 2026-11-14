from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import AdminUser, SalonSettings
from app.repositories.branches import BranchRepository


class BranchNotConfiguredError(AppError):
    status_code = 503
    code = "salon_not_configured"
    message = "Salon is not configured yet. Run `barber init`."


class BranchService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = BranchRepository(session)

    async def default_branch_id(self) -> uuid.UUID:
        branch = await self.repo.get_default()
        if branch is None:
            raise BranchNotConfiguredError()
        return branch.id

    async def branch_for_admin(self, admin: AdminUser) -> uuid.UUID:
        """Staff bound to a branch work in it; owner-level accounts use the default branch.

        When more branches appear, an explicit X-Branch-Id header will be honored here.
        """
        if admin.branch_id is not None:
            return admin.branch_id
        return await self.default_branch_id()

    async def settings(self, branch_id: uuid.UUID) -> SalonSettings:
        settings = await self.repo.get_settings(branch_id)
        if settings is None:
            raise BranchNotConfiguredError()
        return settings
