"""Services (haircuts etc.) and their categories."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationAppError
from app.models import BarberService, Service, ServiceCategory
from app.repositories.catalog import (
    BarberRepository,
    BarberServiceRepository,
    CategoryRepository,
    ServiceRepository,
)
from app.schemas.catalog import (
    ServiceCategoryIn,
    ServiceCategoryPatch,
    ServiceIn,
    ServicePatch,
)
from app.services.audit import Actor, AuditService, diff, snapshot


def effective_price(link: BarberService, service: Service) -> int:
    return link.price if link.price is not None else service.base_price


def effective_duration(link: BarberService, service: Service) -> int:
    return link.duration_min if link.duration_min is not None else service.duration_min


@dataclass(frozen=True, slots=True)
class PublicServiceView:
    service: Service
    duration_min: int
    duration_max_min: int
    price_min: int
    price_max: int


class CatalogService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.categories = CategoryRepository(session)
        self.services = ServiceRepository(session)
        self.barbers = BarberRepository(session)
        self.links = BarberServiceRepository(session)
        self.audit = AuditService(session)

    # ----- categories -----

    async def list_categories(self, branch_id: uuid.UUID) -> list[ServiceCategory]:
        return await self.categories.list_all(branch_id)

    async def create_category(
        self, branch_id: uuid.UUID, data: ServiceCategoryIn, actor: Actor
    ) -> ServiceCategory:
        category = ServiceCategory(branch_id=branch_id, **data.model_dump())
        self.categories.add(category)
        await self.session.flush()
        self.audit.record(
            actor, "category.create", "service_category", category.id, after=snapshot(category)
        )
        await self.session.commit()
        return category

    async def _get_category(self, branch_id: uuid.UUID, category_id: uuid.UUID) -> ServiceCategory:
        category = await self.categories.get(branch_id, category_id)
        if category is None:
            raise NotFoundError("Category not found")
        return category

    async def update_category(
        self,
        branch_id: uuid.UUID,
        category_id: uuid.UUID,
        data: ServiceCategoryPatch,
        actor: Actor,
    ) -> ServiceCategory:
        category = await self._get_category(branch_id, category_id)
        before = snapshot(category)
        for key, value in data.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(category, key, value)
        await self.session.flush()
        old, new = diff(before, snapshot(category))
        if new:
            self.audit.record(
                actor, "category.update", "service_category", category.id, before=old, after=new
            )
        await self.session.commit()
        return category

    async def delete_category(
        self, branch_id: uuid.UUID, category_id: uuid.UUID, actor: Actor
    ) -> None:
        category = await self._get_category(branch_id, category_id)
        self.audit.record(
            actor, "category.delete", "service_category", category.id, before=snapshot(category)
        )
        await self.categories.delete(category)  # services keep living with category_id = NULL
        await self.session.commit()

    # ----- services -----

    async def list_services(
        self,
        branch_id: uuid.UUID,
        *,
        only_active: bool,
        category_id: uuid.UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Service], int]:
        return await self.services.list_page(
            branch_id,
            only_active=only_active,
            category_id=category_id,
            limit=limit,
            offset=offset,
        )

    async def get_service(self, branch_id: uuid.UUID, service_id: uuid.UUID) -> Service:
        service = await self.services.get(branch_id, service_id)
        if service is None:
            raise NotFoundError("Service not found")
        return service

    async def _check_category(self, branch_id: uuid.UUID, category_id: uuid.UUID | None) -> None:
        if category_id is not None and await self.categories.get(branch_id, category_id) is None:
            raise ValidationAppError("Category does not exist", code="category_not_found")

    async def create_service(self, branch_id: uuid.UUID, data: ServiceIn, actor: Actor) -> Service:
        await self._check_category(branch_id, data.category_id)
        service = Service(branch_id=branch_id, **data.model_dump())
        self.services.add(service)
        await self.session.flush()
        self.audit.record(actor, "service.create", "service", service.id, after=snapshot(service))
        await self.session.commit()
        return service

    async def update_service(
        self, branch_id: uuid.UUID, service_id: uuid.UUID, data: ServicePatch, actor: Actor
    ) -> Service:
        service = await self.get_service(branch_id, service_id)
        changes = data.model_dump(exclude_unset=True)
        if "category_id" in changes:
            await self._check_category(branch_id, changes["category_id"])
        before = snapshot(service)
        for key, value in changes.items():
            if value is None and key != "category_id":
                continue  # explicit null only meaningful for category
            setattr(service, key, value)
        await self.session.flush()
        old, new = diff(before, snapshot(service))
        if new:
            self.audit.record(actor, "service.update", "service", service.id, before=old, after=new)
        await self.session.commit()
        return service

    async def deactivate_service(
        self, branch_id: uuid.UUID, service_id: uuid.UUID, actor: Actor
    ) -> None:
        """Soft delete: history (booking_services) keeps referencing it."""
        service = await self.get_service(branch_id, service_id)
        if service.is_active:
            service.is_active = False
            self.audit.record(
                actor,
                "service.deactivate",
                "service",
                service.id,
                before={"is_active": True},
                after={"is_active": False},
            )
            await self.session.commit()

    # ----- public catalog (mini app) -----

    async def public_services(
        self, branch_id: uuid.UUID, barber_id: uuid.UUID | None
    ) -> list[PublicServiceView]:
        """Services bookable online. With barber_id — that barber's prices; without — the
        min..max range across all barbers who perform each service."""
        if barber_id is not None:
            barber = await self.barbers.get(branch_id, barber_id)
            if barber is None or not barber.is_active or not barber.is_bookable_online:
                raise NotFoundError("Barber not found")
            barber_ids: Sequence[uuid.UUID] = [barber_id]
        else:
            barbers, _ = await self.barbers.list_page(
                branch_id, only_active=True, only_bookable=True, limit=1000
            )
            barber_ids = [barber.id for barber in barbers]
        if not barber_ids:
            return []

        pairs = await self.links.list_with_services(barber_ids, only_active=True)
        grouped: dict[uuid.UUID, tuple[Service, list[int], list[int]]] = {}
        for link, service in pairs:
            if service.branch_id != branch_id:
                continue
            _, prices, durations = grouped.setdefault(service.id, (service, [], []))
            prices.append(effective_price(link, service))
            durations.append(effective_duration(link, service))

        views = [
            PublicServiceView(
                service=service,
                duration_min=min(durations),
                duration_max_min=max(durations),
                price_min=min(prices),
                price_max=max(prices),
            )
            for service, prices, durations in grouped.values()
        ]
        views.sort(key=lambda view: (view.service.sort_order, view.service.created_at))
        return views
