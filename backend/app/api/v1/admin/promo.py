"""Promo codes (owner and admin)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import AdminContext, SessionDep, require
from app.core.errors import ConflictError, ErrorResponse, NotFoundError
from app.models import PromoCode
from app.schemas.admin import PromoCodeIn, PromoCodeOut, PromoCodePatch
from app.services.audit import AuditService, diff, snapshot
from app.services.permissions import Perm
from app.services.promo import PromoService, normalize

router = APIRouter(prefix="/promo-codes", tags=["admin-promo"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

CanRead = Annotated[AdminContext, Depends(require(Perm.SETTINGS_READ))]
CanWrite = Annotated[AdminContext, Depends(require(Perm.SETTINGS_WRITE))]


def to_out(promo: PromoCode, uses: int) -> PromoCodeOut:
    return PromoCodeOut.model_validate({**snapshot_fields(promo), "uses": uses})


def snapshot_fields(promo: PromoCode) -> dict[str, object]:
    return {
        name: getattr(promo, name)
        for name in PromoCodeOut.model_fields
        if name != "uses" and hasattr(promo, name)
    }


async def _get(session: SessionDep, ctx: AdminContext, promo_id: uuid.UUID) -> PromoCode:
    promo = await session.get(PromoCode, promo_id)
    if promo is None or promo.branch_id != ctx.branch_id:
        raise NotFoundError("Promo code not found")
    return promo


@router.get("", response_model=list[PromoCodeOut], responses=ERRORS)
async def list_promo_codes(ctx: CanRead, session: SessionDep) -> list[PromoCodeOut]:
    rows = (
        (
            await session.execute(
                select(PromoCode)
                .where(PromoCode.branch_id == ctx.branch_id)
                .order_by(PromoCode.is_active.desc(), PromoCode.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    uses = await PromoService(session).uses([row.id for row in rows])
    return [to_out(row, uses.get(row.id, 0)) for row in rows]


@router.post("", response_model=PromoCodeOut, status_code=201, responses=ERRORS)
async def create_promo_code(body: PromoCodeIn, ctx: CanWrite, session: SessionDep) -> PromoCodeOut:
    code = normalize(body.code)
    taken = await session.scalar(
        select(func.count()).where(
            PromoCode.branch_id == ctx.branch_id, func.upper(PromoCode.code) == code
        )
    )
    if taken:
        raise ConflictError("This code already exists", code="promo_exists")
    promo = PromoCode(branch_id=ctx.branch_id, **{**body.model_dump(), "code": code})
    session.add(promo)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("This code already exists", code="promo_exists") from exc
    AuditService(session).record(
        ctx.actor, "promo.create", "promo_code", promo.id, after=snapshot(promo)
    )
    await session.commit()
    return to_out(promo, 0)


@router.patch("/{promo_id}", response_model=PromoCodeOut, responses=ERRORS)
async def update_promo_code(
    promo_id: uuid.UUID, body: PromoCodePatch, ctx: CanWrite, session: SessionDep
) -> PromoCodeOut:
    promo = await _get(session, ctx, promo_id)
    before = snapshot(promo)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(promo, key, value)
    await session.flush()
    old, new = diff(before, snapshot(promo))
    if new:
        AuditService(session).record(
            ctx.actor, "promo.update", "promo_code", promo.id, before=old, after=new
        )
    await session.commit()
    uses = await PromoService(session).uses([promo.id])
    return to_out(promo, uses.get(promo.id, 0))
