from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Barber, BarberService, Service, ServiceCategory


class BarberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, branch_id: uuid.UUID, barber_id: uuid.UUID) -> Barber | None:
        result = await self.session.execute(
            select(Barber).where(Barber.id == barber_id, Barber.branch_id == branch_id)
        )
        return result.scalar_one_or_none()

    async def list_page(
        self,
        branch_id: uuid.UUID,
        *,
        only_active: bool = False,
        only_bookable: bool = False,
        ids: Sequence[uuid.UUID] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Barber], int]:
        query = select(Barber).where(Barber.branch_id == branch_id)
        if only_active:
            query = query.where(Barber.is_active.is_(True))
        if only_bookable:
            query = query.where(Barber.is_bookable_online.is_(True))
        if ids is not None:
            query = query.where(Barber.id.in_(ids))
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = await self.session.execute(
            query.order_by(Barber.sort_order, Barber.name).limit(limit).offset(offset)
        )
        return list(rows.scalars()), int(total or 0)

    async def ids_performing_all(
        self, branch_id: uuid.UUID, service_ids: Sequence[uuid.UUID]
    ) -> list[uuid.UUID]:
        """Active online-bookable barbers that perform every one of service_ids."""
        query = (
            select(BarberService.barber_id)
            .join(Barber, Barber.id == BarberService.barber_id)
            .where(
                Barber.branch_id == branch_id,
                Barber.is_active.is_(True),
                Barber.is_bookable_online.is_(True),
                BarberService.is_active.is_(True),
                BarberService.service_id.in_(service_ids),
            )
            .group_by(BarberService.barber_id)
            .having(func.count(func.distinct(BarberService.service_id)) == len(set(service_ids)))
        )
        result = await self.session.execute(query)
        return list(result.scalars())

    def add(self, barber: Barber) -> None:
        self.session.add(barber)

    async def delete(self, barber: Barber) -> None:
        await self.session.delete(barber)


class BarberServiceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_with_services(
        self, barber_ids: Sequence[uuid.UUID], *, only_active: bool = False
    ) -> list[tuple[BarberService, Service]]:
        query = (
            select(BarberService, Service)
            .join(Service, Service.id == BarberService.service_id)
            .where(BarberService.barber_id.in_(barber_ids))
        )
        if only_active:
            query = query.where(BarberService.is_active.is_(True), Service.is_active.is_(True))
        result = await self.session.execute(query.order_by(Service.sort_order))
        return [(row[0], row[1]) for row in result.all()]

    async def replace_for_barber(
        self, barber_id: uuid.UUID, items: Sequence[BarberService]
    ) -> None:
        await self.session.execute(
            delete(BarberService).where(BarberService.barber_id == barber_id)
        )
        self.session.add_all(items)


class ServiceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, branch_id: uuid.UUID, service_id: uuid.UUID) -> Service | None:
        result = await self.session.execute(
            select(Service).where(Service.id == service_id, Service.branch_id == branch_id)
        )
        return result.scalar_one_or_none()

    async def get_many(
        self, branch_id: uuid.UUID, service_ids: Sequence[uuid.UUID]
    ) -> list[Service]:
        result = await self.session.execute(
            select(Service).where(Service.branch_id == branch_id, Service.id.in_(service_ids))
        )
        return list(result.scalars())

    async def list_page(
        self,
        branch_id: uuid.UUID,
        *,
        only_active: bool = False,
        category_id: uuid.UUID | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[Service], int]:
        query = select(Service).where(Service.branch_id == branch_id)
        if only_active:
            query = query.where(Service.is_active.is_(True))
        if category_id is not None:
            query = query.where(Service.category_id == category_id)
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = await self.session.execute(
            query.order_by(Service.sort_order, Service.created_at).limit(limit).offset(offset)
        )
        return list(rows.scalars()), int(total or 0)

    def add(self, service: Service) -> None:
        self.session.add(service)

    async def delete(self, service: Service) -> None:
        await self.session.delete(service)


class CategoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, branch_id: uuid.UUID, category_id: uuid.UUID) -> ServiceCategory | None:
        result = await self.session.execute(
            select(ServiceCategory).where(
                ServiceCategory.id == category_id, ServiceCategory.branch_id == branch_id
            )
        )
        return result.scalar_one_or_none()

    async def list_all(self, branch_id: uuid.UUID) -> list[ServiceCategory]:
        result = await self.session.execute(
            select(ServiceCategory)
            .where(ServiceCategory.branch_id == branch_id)
            .order_by(ServiceCategory.sort_order, ServiceCategory.created_at)
        )
        return list(result.scalars())

    def add(self, category: ServiceCategory) -> None:
        self.session.add(category)

    async def delete(self, category: ServiceCategory) -> None:
        await self.session.delete(category)
