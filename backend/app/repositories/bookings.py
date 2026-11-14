from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Barber, Booking, Client
from app.models.enums import ACTIVE_BOOKING_STATUSES, BookingKind, BookingStatus


class BookingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _base(self) -> Select[tuple[Booking]]:
        return select(Booking).options(selectinload(Booking.services))

    async def get(self, branch_id: uuid.UUID, booking_id: uuid.UUID) -> Booking | None:
        result = await self.session.execute(
            self._base().where(Booking.id == booking_id, Booking.branch_id == branch_id)
        )
        return result.scalar_one_or_none()

    async def get_for_client(self, client_id: uuid.UUID, booking_id: uuid.UUID) -> Booking | None:
        """IDOR guard: a client can only ever load their own bookings."""
        result = await self.session.execute(
            self._base().where(
                Booking.id == booking_id,
                Booking.client_id == client_id,
                Booking.kind == BookingKind.APPOINTMENT,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(self, client_id: uuid.UUID, key: str) -> Booking | None:
        result = await self.session.execute(
            self._base().where(Booking.client_id == client_id, Booking.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    async def count_active_upcoming(self, client_id: uuid.UUID, now: datetime) -> int:
        result = await self.session.scalar(
            select(func.count())
            .select_from(Booking)
            .where(
                Booking.client_id == client_id,
                Booking.status.in_(ACTIVE_BOOKING_STATUSES),
                Booking.start_at > now,
            )
        )
        return int(result or 0)

    async def list_for_client(
        self,
        client_id: uuid.UUID,
        *,
        upcoming: bool,
        now: datetime,
        limit: int,
        after: tuple[datetime, uuid.UUID] | None,
    ) -> list[Booking]:
        """Upcoming: active, soonest first. Past: everything else, newest first. Keyset paging."""
        query = self._base().where(
            Booking.client_id == client_id, Booking.kind == BookingKind.APPOINTMENT
        )
        active_future = and_(Booking.status.in_(ACTIVE_BOOKING_STATUSES), Booking.end_at > now)
        if upcoming:
            query = query.where(active_future).order_by(Booking.start_at, Booking.id)
            if after:
                query = query.where(
                    or_(
                        Booking.start_at > after[0],
                        and_(Booking.start_at == after[0], Booking.id > after[1]),
                    )
                )
        else:
            query = query.where(~active_future).order_by(Booking.start_at.desc(), Booking.id.desc())
            if after:
                query = query.where(
                    or_(
                        Booking.start_at < after[0],
                        and_(Booking.start_at == after[0], Booking.id < after[1]),
                    )
                )
        result = await self.session.execute(query.limit(limit))
        return list(result.scalars())

    async def last_visit(self, client_id: uuid.UUID, now: datetime) -> Booking | None:
        result = await self.session.execute(
            self._base()
            .where(
                Booking.client_id == client_id,
                Booking.kind == BookingKind.APPOINTMENT,
                Booking.status.in_((BookingStatus.COMPLETED, BookingStatus.CONFIRMED)),
                Booking.start_at < now,
            )
            .order_by(Booking.start_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def search(
        self,
        branch_id: uuid.UUID,
        *,
        date_from: datetime | None,
        date_to: datetime | None,
        barber_ids: Sequence[uuid.UUID] | None,
        statuses: Sequence[BookingStatus] | None,
        client_id: uuid.UUID | None,
        include_blocks: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[Booking], int]:
        query = self._base().where(Booking.branch_id == branch_id)
        if date_from is not None:
            query = query.where(Booking.end_at > date_from)
        if date_to is not None:
            query = query.where(Booking.start_at < date_to)
        if barber_ids is not None:
            query = query.where(Booking.barber_id.in_(barber_ids))
        if statuses:
            query = query.where(Booking.status.in_(statuses))
        if client_id is not None:
            query = query.where(Booking.client_id == client_id)
        if not include_blocks:
            query = query.where(Booking.kind == BookingKind.APPOINTMENT)
        total = await self.session.scalar(
            select(func.count()).select_from(query.order_by(None).subquery())
        )
        result = await self.session.execute(
            query.order_by(Booking.start_at, Booking.id).limit(limit).offset(offset)
        )
        return list(result.scalars()), int(total or 0)

    async def clients_by_id(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Client]:
        if not ids:
            return {}
        result = await self.session.execute(select(Client).where(Client.id.in_(set(ids))))
        return {client.id: client for client in result.scalars()}

    async def barbers_by_id(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Barber]:
        if not ids:
            return {}
        result = await self.session.execute(select(Barber).where(Barber.id.in_(set(ids))))
        return {barber.id: barber for barber in result.scalars()}

    def add(self, booking: Booking) -> None:
        self.session.add(booking)
