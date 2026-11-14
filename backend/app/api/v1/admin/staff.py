from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import AdminContext, NowDep, SessionDep, require
from app.core.errors import ErrorResponse
from app.models import AdminUser
from app.schemas.admin import AuditOut, AuditPage, StaffIn, StaffOut, StaffPatch
from app.services.permissions import Perm
from app.services.staff import StaffService

router = APIRouter(tags=["admin-staff"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

OwnerStaff = Annotated[AdminContext, Depends(require(Perm.STAFF_MANAGE))]
OwnerAudit = Annotated[AdminContext, Depends(require(Perm.AUDIT_READ))]


def to_out(account: AdminUser) -> StaffOut:
    return StaffOut(
        id=account.id,
        login=account.login,
        full_name=account.full_name,
        role=account.role,
        barber_id=account.barber_id,
        language=account.language,
        is_active=account.is_active,
        telegram_linked=account.user_id is not None,
        last_login_at=account.last_login_at,
        created_at=account.created_at,
    )


@router.get("/admin-users", response_model=list[StaffOut], responses=ERRORS)
async def list_staff(ctx: OwnerStaff, session: SessionDep) -> list[StaffOut]:
    return [to_out(account) for account in await StaffService(session).list_all()]


@router.post("/admin-users", response_model=StaffOut, status_code=201, responses=ERRORS)
async def create_staff(body: StaffIn, ctx: OwnerStaff, session: SessionDep) -> StaffOut:
    return to_out(await StaffService(session).create(ctx.branch_id, body, ctx.actor))


@router.patch("/admin-users/{account_id}", response_model=StaffOut, responses=ERRORS)
async def update_staff(
    account_id: uuid.UUID, body: StaffPatch, ctx: OwnerStaff, session: SessionDep, now: NowDep
) -> StaffOut:
    """Password, role or deactivation changes sign the account out everywhere."""
    return to_out(
        await StaffService(session).update(ctx.branch_id, account_id, body, ctx.actor, now)
    )


@router.get("/audit-log", response_model=AuditPage, responses=ERRORS)
async def audit_log(
    ctx: OwnerAudit,
    session: SessionDep,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    action: Annotated[str | None, Query(max_length=64, description="Prefix, e.g. 'bonus.'")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditPage:
    rows, total = await StaffService(session).audit_log(
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        action=action,
        limit=limit,
        offset=offset,
    )
    return AuditPage(
        items=[
            AuditOut(
                id=entry.id,
                actor_type=entry.actor_type,
                actor_id=entry.actor_id,
                actor_name=login,
                action=entry.action,
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                before=entry.before,
                after=entry.after,
                ip=entry.ip,
                created_at=entry.created_at,
            )
            for entry, login in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
