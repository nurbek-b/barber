from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import AdminContext, SessionDep, require
from app.core.errors import ErrorResponse
from app.models import SalonSettings
from app.notify.templates import DEFAULTS
from app.schemas.admin import SalonSettingsIn, SalonSettingsOut, TemplateDefaultsOut
from app.services.audit import AuditService, diff, snapshot
from app.services.branches import BranchService
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
