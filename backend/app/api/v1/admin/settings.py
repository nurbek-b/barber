from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from app.api.deps import AdminContext, SessionDep, SettingsDep, require
from app.core.errors import ErrorResponse
from app.models import SalonSettings
from app.notify.templates import DEFAULTS
from app.schemas.admin import GalleryPut, SalonSettingsIn, SalonSettingsOut, TemplateDefaultsOut
from app.services.audit import AuditService, diff, snapshot
from app.services.branches import BranchService
from app.services.branding import BrandingService
from app.services.permissions import Perm

router = APIRouter(prefix="/settings", tags=["admin-settings"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

CanRead = Annotated[AdminContext, Depends(require(Perm.SETTINGS_READ))]
CanWrite = Annotated[AdminContext, Depends(require(Perm.SETTINGS_WRITE))]


def to_out(salon: SalonSettings) -> SalonSettingsOut:
    return SalonSettingsOut(
        name=salon.name,
        timezone=salon.timezone,
        currency=salon.currency,
        default_language=salon.default_language,
        slot_step_min=salon.slot_step_min,
        buffer_min=salon.buffer_min,
        min_lead_time_min=salon.min_lead_time_min,
        max_days_ahead=salon.max_days_ahead,
        cancel_min_hours=salon.cancel_min_hours,
        reschedule_min_hours=salon.reschedule_min_hours,
        max_active_bookings_per_client=salon.max_active_bookings_per_client,
        reminder_offsets_min=list(salon.reminder_offsets_min or []),
        admin_chat_id=salon.admin_chat_id,
        notify_barbers=salon.notify_barbers,
        notification_templates=salon.notification_templates or {},
        contacts={str(k): str(v) for k, v in (salon.contacts or {}).items()},
        logo_url=salon.logo_url,
        gallery=list(salon.gallery or []),
        review_links={str(k): str(v) for k, v in (salon.review_links or {}).items()},
        payment_qr_url=salon.payment_qr_url,
        payment_note=salon.payment_note,
        prepay_percent=salon.prepay_percent,
        prepay_after_no_shows=salon.prepay_after_no_shows,
        prepay_timeout_min=salon.prepay_timeout_min,
        revisit_after_days=salon.revisit_after_days,
    )


@router.get("/salon", response_model=SalonSettingsOut, responses=ERRORS)
async def get_salon(ctx: CanRead, session: SessionDep) -> SalonSettingsOut:
    return to_out(await BranchService(session).settings(ctx.branch_id))


@router.put("/salon", response_model=SalonSettingsOut, responses=ERRORS)
async def put_salon(body: SalonSettingsIn, ctx: CanWrite, session: SessionDep) -> SalonSettingsOut:
    """Grid step, buffer and timezone are part of the slot cache key, so changes apply at
    once. Existing bookings keep their stored blocked_until."""
    salon = await BranchService(session).settings(ctx.branch_id)
    before = snapshot(salon)
    for key, value in body.model_dump().items():
        setattr(salon, key, value)
    await session.flush()
    old, new = diff(before, snapshot(salon))
    if new:
        AuditService(session).record(
            ctx.actor, "salon_settings.update", "branch", ctx.branch_id, before=old, after=new
        )
    await session.commit()
    return to_out(salon)


@router.get("/notification-templates", response_model=TemplateDefaultsOut, responses=ERRORS)
async def template_defaults(ctx: CanRead) -> TemplateDefaultsOut:
    """Built-in texts the salon may override (placeholders like {when}, {barber})."""
    return TemplateDefaultsOut(templates=DEFAULTS)


Image = Annotated[UploadFile, File(description="JPEG, PNG or WebP, up to 5 MB")]


@router.post("/salon/logo", response_model=SalonSettingsOut, responses=ERRORS)
async def upload_logo(
    file: Image, ctx: CanWrite, session: SessionDep, settings: SettingsDep
) -> SalonSettingsOut:
    content = await file.read(settings.max_upload_bytes + 1)
    return to_out(
        await BrandingService(session, settings).set_logo(ctx.branch_id, content, ctx.actor)
    )


@router.delete("/salon/logo", response_model=SalonSettingsOut, responses=ERRORS)
async def delete_logo(
    ctx: CanWrite, session: SessionDep, settings: SettingsDep
) -> SalonSettingsOut:
    return to_out(await BrandingService(session, settings).remove_logo(ctx.branch_id, ctx.actor))


@router.post("/salon/gallery", response_model=SalonSettingsOut, responses=ERRORS)
async def add_gallery_photo(
    file: Image, ctx: CanWrite, session: SessionDep, settings: SettingsDep
) -> SalonSettingsOut:
    content = await file.read(settings.max_upload_bytes + 1)
    return to_out(
        await BrandingService(session, settings).add_photo(ctx.branch_id, content, ctx.actor)
    )


@router.put("/salon/gallery", response_model=SalonSettingsOut, responses=ERRORS)
async def put_gallery(
    body: GalleryPut, ctx: CanWrite, session: SessionDep, settings: SettingsDep
) -> SalonSettingsOut:
    return to_out(
        await BrandingService(session, settings).set_gallery(ctx.branch_id, body.urls, ctx.actor)
    )
