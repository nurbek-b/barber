"""Client management for staff: search, card, edits, blocking."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.models import Booking, Client, User
from app.models.enums import ACTIVE_BOOKING_STATUSES, BookingKind, BookingStatus
from app.schemas.admin import ClientIn, ClientPatch
from app.services.audit import Actor, AuditService, diff, snapshot
from app.services.client_registry import new_referral_code, normalize_phone

SortField = Literal["name", "created_at", "visits_count", "total_spent", "last_visit_at"]


@dataclass(frozen=True, slots=True)
class ClientListItem:
    client: Client
    username: str | None
    last_visit_at: datetime | None


@dataclass(frozen=True, slots=True)
class ClientDetails:
    item: ClientListItem
    upcoming_count: int


ICU = "und-x-icu"


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ClientAdminService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    def _last_visit(self) -> Select[tuple[uuid.UUID | None, datetime]]:
        return (
            select(Booking.client_id, func.max(Booking.start_at).label("last_visit_at"))
            .where(
                Booking.status == BookingStatus.COMPLETED, Booking.kind == BookingKind.APPOINTMENT
            )
            .group_by(Booking.client_id)
        )

    async def search(
        self,
        branch_id: uuid.UUID,
        *,
        q: str | None,
        tag: str | None,
        blocked: bool | None,
        level_id: uuid.UUID | None,
        sort: SortField,
        descending: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[ClientListItem], int]:
        last = self._last_visit().subquery()
        query = (
            select(Client, User.username, last.c.last_visit_at)
            .outerjoin(User, User.id == Client.user_id)
            .outerjoin(last, last.c.client_id == Client.id)
            .where(Client.branch_id == branch_id)
        )
        if q:
            # ICU collation: Unicode-aware lower() even when the DB locale is "C" (Cyrillic names)
            pattern = f"%{_escape_like(q.strip().lower())}%"
            digits = "".join(ch for ch in q if ch.isdigit())
            conditions = [
                func.lower(Client.name.collate(ICU)).like(pattern, escape="\\"),
                func.lower(User.username).like(pattern, escape="\\"),
            ]
            if len(digits) >= 3:
                conditions.append(Client.phone.like(f"%{digits}%"))
            query = query.where(or_(*conditions))
        if tag:
            query = query.where(Client.tags.contains([tag.strip().lower()]))
        if blocked is not None:
            query = query.where(Client.is_blocked.is_(blocked))
        if level_id is not None:
            query = query.where(Client.level_id == level_id)

        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        column = {
            "name": Client.name,
            "created_at": Client.created_at,
            "visits_count": Client.visits_count,
            "total_spent": Client.total_spent,
            "last_visit_at": last.c.last_visit_at,
        }[sort]
        order = column.desc().nulls_last() if descending else column.asc().nulls_last()
        rows = await self.session.execute(
            query.order_by(order, Client.id).limit(limit).offset(offset)
        )
        items = [ClientListItem(row[0], row[1], row[2]) for row in rows.all()]
        return items, int(total or 0)

    async def _get(self, branch_id: uuid.UUID, client_id: uuid.UUID) -> Client:
        client = await self.session.get(Client, client_id)
        if client is None or client.branch_id != branch_id:
            raise NotFoundError("Client not found")
        return client

    async def card(
        self, branch_id: uuid.UUID, client_id: uuid.UUID, now: datetime
    ) -> ClientDetails:
        client = await self._get(branch_id, client_id)
        username = None
        if client.user_id:
            user = await self.session.get(User, client.user_id)
            username = user.username if user else None
        last = await self.session.scalar(
            select(func.max(Booking.start_at)).where(
                Booking.client_id == client.id, Booking.status == BookingStatus.COMPLETED
            )
        )
        upcoming = await self.session.scalar(
            select(func.count())
            .select_from(Booking)
            .where(
                Booking.client_id == client.id,
                Booking.status.in_(ACTIVE_BOOKING_STATUSES),
                Booking.start_at > now,
            )
        )
        return ClientDetails(ClientListItem(client, username, last), int(upcoming or 0))

    async def _phone_taken(
        self, branch_id: uuid.UUID, phone: str, exclude: uuid.UUID | None = None
    ) -> bool:
        query = select(Client.id).where(Client.branch_id == branch_id, Client.phone == phone)
        if exclude is not None:
            query = query.where(Client.id != exclude)
        return await self.session.scalar(query.limit(1)) is not None

    async def create(self, branch_id: uuid.UUID, data: ClientIn, actor: Actor) -> Client:
        phone = normalize_phone(data.phone)
        if await self._phone_taken(branch_id, phone):
            raise ConflictError("A client with this phone already exists", code="phone_taken")
        client = Client(
            branch_id=branch_id,
            name=data.name.strip(),
            phone=phone,
            birthday=data.birthday,
            language=data.language,
            tags=data.tags,
            notes=data.notes,
            referral_code=new_referral_code(),
        )
        self.session.add(client)
        await self.session.flush()
        self.audit.record(actor, "client.create", "client", client.id, after=snapshot(client))
        await self.session.commit()
        return client

    async def update(
        self, branch_id: uuid.UUID, client_id: uuid.UUID, data: ClientPatch, actor: Actor
    ) -> Client:
        client = await self._get(branch_id, client_id)
        before = snapshot(client)
        changes = data.model_dump(exclude_unset=True)
        if changes.get("phone"):
            changes["phone"] = normalize_phone(changes["phone"])
            if await self._phone_taken(branch_id, changes["phone"], exclude=client.id):
                raise ConflictError("A client with this phone already exists", code="phone_taken")
        for key, value in changes.items():
            if value is None and key in ("name", "language", "tags"):
                continue
            setattr(client, key, value)
        await self.session.flush()
        old, new = diff(before, snapshot(client))
        if new:
            self.audit.record(actor, "client.update", "client", client.id, before=old, after=new)
        await self.session.commit()
        return client

    async def set_blocked(
        self,
        branch_id: uuid.UUID,
        client_id: uuid.UUID,
        blocked: bool,
        reason: str | None,
        actor: Actor,
    ) -> Client:
        client = await self._get(branch_id, client_id)
        if client.is_blocked != blocked:
            client.is_blocked = blocked
            self.audit.record(
                actor,
                "client.block" if blocked else "client.unblock",
                "client",
                client.id,
                before={"is_blocked": not blocked},
                after={"is_blocked": blocked, "reason": reason},
            )
            await self.session.commit()
        return client
