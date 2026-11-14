from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Client, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_telegram_id_for_update(self, telegram_id: int) -> User | None:
        result = await self.session.execute(
            select(User).where(User.telegram_id == telegram_id).with_for_update()
        )
        return result.scalar_one_or_none()

    def add(self, user: User) -> None:
        self.session.add(user)


class ClientRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_user(self, branch_id: uuid.UUID, user_id: uuid.UUID) -> Client | None:
        result = await self.session.execute(
            select(Client).where(Client.branch_id == branch_id, Client.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_referral_code(self, branch_id: uuid.UUID, code: str) -> Client | None:
        result = await self.session.execute(
            select(Client).where(Client.branch_id == branch_id, Client.referral_code == code)
        )
        return result.scalar_one_or_none()

    async def referral_code_exists(self, code: str) -> bool:
        result = await self.session.execute(
            select(Client.id).where(Client.referral_code == code).limit(1)
        )
        return result.first() is not None

    def add(self, client: Client) -> None:
        self.session.add(client)
