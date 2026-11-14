"""Admin notification feed with per-admin read marks."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Select, and_, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models import AdminUser, Notification, NotificationRead
from app.models.enums import AdminRole


@dataclass(frozen=True, slots=True)
class FeedItem:
    notification: Notification
    read: bool


def visible_to(admin: AdminUser, payload: dict[str, object]) -> bool:
    """Barbers only see events about their own bookings."""
    if admin.role is not AdminRole.BARBER:
        return True
    return admin.barber_id is not None and payload.get("barber_id") == str(admin.barber_id)


class NotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _scope(self, branch_id: uuid.UUID, admin: AdminUser) -> Select[tuple[Notification]]:
        query = select(Notification).where(Notification.branch_id == branch_id)
        if admin.role is AdminRole.BARBER:
            query = query.where(Notification.payload["barber_id"].astext == str(admin.barber_id))
        return query

    async def feed(
        self,
        branch_id: uuid.UUID,
        admin: AdminUser,
        *,
        limit: int,
        before: datetime | None,
        since: datetime | None,
        unread_only: bool,
    ) -> list[FeedItem]:
        read_join = and_(
            NotificationRead.notification_id == Notification.id,
            NotificationRead.admin_user_id == admin.id,
        )
        query = (
            self._scope(branch_id, admin)
            .add_columns(NotificationRead.read_at)
            .outerjoin(NotificationRead, read_join)
        )
        if before is not None:
            query = query.where(Notification.created_at < before)
        if since is not None:
            query = query.where(Notification.created_at > since)
        if unread_only:
            query = query.where(NotificationRead.read_at.is_(None))
        rows = await self.session.execute(
            query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
        )
        return [FeedItem(notification=row[0], read=row[1] is not None) for row in rows.all()]

    async def unread_count(self, branch_id: uuid.UUID, admin: AdminUser) -> int:
        query = (
            self._scope(branch_id, admin)
            .outerjoin(
                NotificationRead,
                and_(
                    NotificationRead.notification_id == Notification.id,
                    NotificationRead.admin_user_id == admin.id,
                ),
            )
            .where(NotificationRead.read_at.is_(None))
        )
        result = await self.session.scalar(
            select(func.count()).select_from(query.with_only_columns(Notification.id).subquery())
        )
        return int(result or 0)

    async def mark_read(
        self, branch_id: uuid.UUID, admin: AdminUser, notification_id: uuid.UUID
    ) -> None:
        exists = await self.session.scalar(
            self._scope(branch_id, admin)
            .where(Notification.id == notification_id)
            .with_only_columns(Notification.id)
        )
        if exists is None:
            raise NotFoundError("Notification not found")
        await self.session.execute(
            insert(NotificationRead)
            .values(
                notification_id=notification_id,
                admin_user_id=admin.id,
                read_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing()
        )
        await self.session.commit()

    async def mark_all_read(self, branch_id: uuid.UUID, admin: AdminUser) -> int:
        unread = (
            self._scope(branch_id, admin)
            .with_only_columns(Notification.id)
            .outerjoin(
                NotificationRead,
                and_(
                    NotificationRead.notification_id == Notification.id,
                    NotificationRead.admin_user_id == admin.id,
                ),
            )
            .where(NotificationRead.read_at.is_(None))
        )
        ids = list((await self.session.execute(unread)).scalars())
        if ids:
            now = datetime.now(UTC)
            await self.session.execute(
                insert(NotificationRead)
                .values(
                    [
                        {"notification_id": nid, "admin_user_id": admin.id, "read_at": now}
                        for nid in ids
                    ]
                )
                .on_conflict_do_nothing()
            )
            await self.session.commit()
        return len(ids)
