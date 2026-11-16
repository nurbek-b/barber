"""Salon branding for the Mini App: logo and a small photo gallery (stored like barber photos)."""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ValidationAppError
from app.core.media import get_media_storage, key_from_url, url_for
from app.models import Barber, SalonSettings
from app.services.audit import Actor, AuditService
from app.services.barbers import PayloadTooLargeError, detect_image_type
from app.services.branches import BranchService

MAX_GALLERY = 8


class BrandingService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.audit = AuditService(session)

    async def _salon(self, branch_id: uuid.UUID) -> SalonSettings:
        return await BranchService(self.session).settings(branch_id)

    async def _store(self, content: bytes) -> str:
        if len(content) > self.settings.max_upload_bytes:
            raise PayloadTooLargeError()
        extension = detect_image_type(content[:16])
        if extension is None:
            raise ValidationAppError("Only JPEG, PNG or WebP images", code="unsupported_image")
        key = f"salon/{uuid.uuid4().hex}-{secrets.token_hex(4)}.{extension}"
        await get_media_storage(self.settings).save(key, content)
        return url_for(self.settings, key)

    async def _drop(self, urls: Sequence[str | None]) -> None:
        storage = get_media_storage(self.settings)
        for url in urls:
            key = key_from_url(self.settings, url)
            if key:
                await storage.delete(key)

    async def set_logo(self, branch_id: uuid.UUID, content: bytes, actor: Actor) -> SalonSettings:
        salon = await self._salon(branch_id)
        url = await self._store(content)
        old = salon.logo_url
        salon.logo_url = url
        self.audit.record(
            actor,
            "salon.logo",
            "branch",
            branch_id,
            before={"logo_url": old},
            after={"logo_url": url},
        )
        await self.session.commit()
        await self._drop([old])
        return salon

    async def remove_logo(self, branch_id: uuid.UUID, actor: Actor) -> SalonSettings:
        salon = await self._salon(branch_id)
        old = salon.logo_url
        if old:
            salon.logo_url = None
            self.audit.record(
                actor, "salon.logo", "branch", branch_id, before={"logo_url": old}, after={}
            )
            await self.session.commit()
            await self._drop([old])
        return salon

    async def add_photo(self, branch_id: uuid.UUID, content: bytes, actor: Actor) -> SalonSettings:
        salon = await self._salon(branch_id)
        if len(salon.gallery or []) >= MAX_GALLERY:
            raise ValidationAppError(
                f"The gallery holds up to {MAX_GALLERY} photos", code="gallery_full"
            )
        url = await self._store(content)
        salon.gallery = [*(salon.gallery or []), url]
        self.audit.record(actor, "salon.gallery_add", "branch", branch_id, after={"url": url})
        await self.session.commit()
        return salon

    async def set_gallery(
        self, branch_id: uuid.UUID, urls: Sequence[str], actor: Actor
    ) -> SalonSettings:
        """Reorder or remove photos: `urls` must be a subset of the current gallery."""
        salon = await self._salon(branch_id)
        current = list(salon.gallery or [])
        unknown = [url for url in urls if url not in current]
        if unknown or len(set(urls)) != len(urls):
            raise ValidationAppError("Unknown or duplicate photo", code="gallery_invalid")
        removed = [url for url in current if url not in urls]
        salon.gallery = list(urls)
        self.audit.record(
            actor,
            "salon.gallery",
            "branch",
            branch_id,
            before={"gallery": current},
            after={"gallery": list(urls)},
        )
        await self.session.commit()
        await self._drop(removed)
        return salon

    # ---- bank QR for payments (the salon's, or a barber's own) --------------------------

    async def set_payment_qr(
        self, branch_id: uuid.UUID, content: bytes, actor: Actor, barber: Barber | None = None
    ) -> None:
        url = await self._store(content)
        if barber is not None:
            old, barber.payment_qr_url = barber.payment_qr_url, url
            entity, entity_id = "barber", barber.id
        else:
            salon = await self._salon(branch_id)
            old, salon.payment_qr_url = salon.payment_qr_url, url
            entity, entity_id = "branch", branch_id
        self.audit.record(
            actor, "payment_qr.set", entity, entity_id, before={"url": old}, after={"url": url}
        )
        await self.session.commit()
        await self._drop([old])

    async def remove_payment_qr(
        self, branch_id: uuid.UUID, actor: Actor, barber: Barber | None = None
    ) -> None:
        if barber is not None:
            old, barber.payment_qr_url = barber.payment_qr_url, None
            entity, entity_id = "barber", barber.id
        else:
            salon = await self._salon(branch_id)
            old, salon.payment_qr_url = salon.payment_qr_url, None
            entity, entity_id = "branch", branch_id
        if old:
            self.audit.record(actor, "payment_qr.remove", entity, entity_id, before={"url": old})
            await self.session.commit()
            await self._drop([old])
