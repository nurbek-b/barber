from __future__ import annotations

import asyncio
import secrets
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, NotFoundError, ValidationAppError
from app.models import Barber, BarberService, Service
from app.repositories.catalog import BarberRepository, BarberServiceRepository, ServiceRepository
from app.schemas.catalog import BarberIn, BarberPatch, BarberServiceIn
from app.services.audit import Actor, AuditService, diff, snapshot
from app.services.catalog import effective_duration, effective_price


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"
    message = "File is too large"


@dataclass(frozen=True, slots=True)
class BarberServiceView:
    link: BarberService
    service: Service

    @property
    def effective_price(self) -> int:
        return effective_price(self.link, self.service)

    @property
    def effective_duration_min(self) -> int:
        return effective_duration(self.link, self.service)


def _write_file(directory: Path, filename: str, content: bytes) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_bytes(content)


def _remove_file(directory: Path, filename: str) -> None:
    """Delete a previous upload; refuses anything outside `directory` (path traversal)."""
    root = directory.resolve()
    path = (root / filename).resolve()
    if path.parent == root:
        path.unlink(missing_ok=True)


def detect_image_type(head: bytes) -> str | None:
    """Trust magic bytes, not the client-provided Content-Type."""
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


class BarbersService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings
        self.barbers = BarberRepository(session)
        self.links = BarberServiceRepository(session)
        self.services = ServiceRepository(session)
        self.audit = AuditService(session)

    async def get(self, branch_id: uuid.UUID, barber_id: uuid.UUID) -> Barber:
        barber = await self.barbers.get(branch_id, barber_id)
        if barber is None:
            raise NotFoundError("Barber not found")
        return barber

    async def list_page(
        self,
        branch_id: uuid.UUID,
        *,
        only_active: bool = False,
        ids: Sequence[uuid.UUID] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Barber], int]:
        return await self.barbers.list_page(
            branch_id, only_active=only_active, ids=ids, limit=limit, offset=offset
        )

    async def list_public(
        self, branch_id: uuid.UUID, service_ids: Sequence[uuid.UUID] | None
    ) -> list[Barber]:
        ids: Sequence[uuid.UUID] | None = None
        if service_ids:
            ids = await self.barbers.ids_performing_all(branch_id, service_ids)
            if not ids:
                return []
        barbers, _ = await self.barbers.list_page(
            branch_id, only_active=True, only_bookable=True, ids=ids, limit=1000
        )
        return barbers

    async def services_of(self, barber_id: uuid.UUID) -> list[BarberServiceView]:
        pairs = await self.links.list_with_services([barber_id])
        return [BarberServiceView(link=link, service=service) for link, service in pairs]

    async def _build_links(
        self, branch_id: uuid.UUID, barber_id: uuid.UUID, items: Sequence[BarberServiceIn]
    ) -> list[BarberService]:
        ids = [item.service_id for item in items]
        found = {service.id for service in await self.services.get_many(branch_id, ids)}
        missing = [str(service_id) for service_id in ids if service_id not in found]
        if missing:
            raise ValidationAppError(
                "Unknown services", code="service_not_found", details={"service_ids": missing}
            )
        return [
            BarberService(
                barber_id=barber_id,
                service_id=item.service_id,
                price=item.price,
                duration_min=item.duration_min,
                is_active=item.is_active,
            )
            for item in items
        ]

    async def create(self, branch_id: uuid.UUID, data: BarberIn, actor: Actor) -> Barber:
        barber = Barber(branch_id=branch_id, **data.model_dump(exclude={"services"}))
        self.barbers.add(barber)
        await self.session.flush()
        links = await self._build_links(branch_id, barber.id, data.services)
        self.session.add_all(links)
        await self.session.flush()
        self.audit.record(
            actor,
            "barber.create",
            "barber",
            barber.id,
            after={**snapshot(barber), "services": [snapshot(link) for link in links]},
        )
        await self.session.commit()
        return barber

    async def update(
        self, branch_id: uuid.UUID, barber_id: uuid.UUID, data: BarberPatch, actor: Actor
    ) -> Barber:
        barber = await self.get(branch_id, barber_id)
        before = snapshot(barber)
        for key, value in data.model_dump(exclude_unset=True).items():
            if value is None and key != "telegram_chat_id":
                continue
            setattr(barber, key, value)
        await self.session.flush()
        old, new = diff(before, snapshot(barber))
        if new:
            self.audit.record(actor, "barber.update", "barber", barber.id, before=old, after=new)
        await self.session.commit()
        return barber

    async def replace_services(
        self,
        branch_id: uuid.UUID,
        barber_id: uuid.UUID,
        items: Sequence[BarberServiceIn],
        actor: Actor,
    ) -> list[BarberServiceView]:
        barber = await self.get(branch_id, barber_id)
        before = [snapshot(view.link) for view in await self.services_of(barber.id)]
        links = await self._build_links(branch_id, barber.id, items)
        await self.links.replace_for_barber(barber.id, links)
        await self.session.flush()
        self.audit.record(
            actor,
            "barber.services",
            "barber",
            barber.id,
            before={"services": before},
            after={"services": [snapshot(link) for link in links]},
        )
        await self.session.commit()
        return await self.services_of(barber.id)

    async def deactivate(self, branch_id: uuid.UUID, barber_id: uuid.UUID, actor: Actor) -> None:
        """Soft delete: bookings history keeps referencing the barber."""
        barber = await self.get(branch_id, barber_id)
        if barber.is_active:
            barber.is_active = False
            barber.is_bookable_online = False
            self.audit.record(
                actor,
                "barber.deactivate",
                "barber",
                barber.id,
                before={"is_active": True},
                after={"is_active": False},
            )
            await self.session.commit()

    async def set_photo(
        self, branch_id: uuid.UUID, barber_id: uuid.UUID, content: bytes, actor: Actor
    ) -> Barber:
        if self.settings is None:
            raise RuntimeError("settings are required for uploads")
        if len(content) > self.settings.max_upload_bytes:
            raise PayloadTooLargeError()
        extension = detect_image_type(content[:16])
        if extension is None:
            raise ValidationAppError("Only JPEG, PNG or WebP images", code="unsupported_image")

        barber = await self.get(branch_id, barber_id)
        target_dir = Path(self.settings.media_dir) / "barbers"
        filename = f"{barber.id}-{secrets.token_hex(6)}.{extension}"
        await asyncio.to_thread(_write_file, target_dir, filename, content)

        old_url = barber.photo_url
        barber.photo_url = f"{self.settings.media_url_prefix}/barbers/{filename}"
        self.audit.record(
            actor,
            "barber.photo",
            "barber",
            barber.id,
            before={"photo_url": old_url},
            after={"photo_url": barber.photo_url},
        )
        await self.session.commit()

        prefix = f"{self.settings.media_url_prefix}/barbers/"
        if old_url and old_url.startswith(prefix):
            await asyncio.to_thread(_remove_file, target_dir, old_url.removeprefix(prefix))
        return barber
