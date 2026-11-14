from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import AdminContext, NowDep, SessionDep, require
from app.api.v1.bonus_views import level_out, tx_out
from app.core.errors import ErrorResponse, NotFoundError
from app.models import Client, LoyaltyLevel
from app.schemas.bonus import (
    AdjustIn,
    BonusSettingsIn,
    BonusSettingsOut,
    BonusTransactionOut,
    ClientBonusOut,
    LevelIn,
    LevelOut,
)
from app.services.audit import AuditService, diff, snapshot
from app.services.bonus import BonusService
from app.services.bonus_ledger import BonusLedger
from app.services.permissions import Perm

router = APIRouter(tags=["admin-bonus"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

CanRead = Annotated[AdminContext, Depends(require(Perm.SETTINGS_READ))]
OwnerOnly = Annotated[AdminContext, Depends(require(Perm.BONUS_SETTINGS_WRITE))]
CanAdjust = Annotated[AdminContext, Depends(require(Perm.BONUS_ADJUST))]
CanReadClients = Annotated[AdminContext, Depends(require(Perm.CLIENTS_READ))]


# ---------------- settings ----------------


@router.get("/settings/bonus", response_model=BonusSettingsOut, responses=ERRORS)
async def get_bonus_settings(ctx: CanRead, session: SessionDep) -> BonusSettingsOut:
    return BonusSettingsOut.model_validate(await BonusService(session).settings(ctx.branch_id))


@router.put("/settings/bonus", response_model=BonusSettingsOut, responses=ERRORS)
async def put_bonus_settings(
    body: BonusSettingsIn, ctx: OwnerOnly, session: SessionDep
) -> BonusSettingsOut:
    """Owner only. Changes apply to future operations; existing lots keep their expiry."""
    settings = await BonusService(session).settings(ctx.branch_id)
    before = snapshot(settings)
    for key, value in body.model_dump().items():
        setattr(settings, key, value)
    await session.flush()
    old, new = diff(before, snapshot(settings))
    if new:
        AuditService(session).record(
            ctx.actor, "bonus_settings.update", "branch", ctx.branch_id, before=old, after=new
        )
    await session.commit()
    return BonusSettingsOut.model_validate(settings)


# ---------------- levels ----------------


@router.get("/loyalty-levels", response_model=list[LevelOut], responses=ERRORS)
async def list_levels(ctx: CanRead, session: SessionDep) -> list[LevelOut]:
    return [
        LevelOut.model_validate(level)
        for level in await BonusService(session).levels(ctx.branch_id)
    ]


@router.post("/loyalty-levels", response_model=LevelOut, status_code=201, responses=ERRORS)
async def create_level(body: LevelIn, ctx: OwnerOnly, session: SessionDep) -> LevelOut:
    level = LoyaltyLevel(branch_id=ctx.branch_id, **body.model_dump())
    session.add(level)
    await session.flush()
    AuditService(session).record(
        ctx.actor, "loyalty_level.create", "loyalty_level", level.id, after=snapshot(level)
    )
    await session.commit()
    return LevelOut.model_validate(level)


async def _level(session: SessionDep, ctx: AdminContext, level_id: uuid.UUID) -> LoyaltyLevel:
    level = await session.get(LoyaltyLevel, level_id)
    if level is None or level.branch_id != ctx.branch_id:
        raise NotFoundError("Level not found")
    return level


@router.put("/loyalty-levels/{level_id}", response_model=LevelOut, responses=ERRORS)
async def update_level(
    level_id: uuid.UUID, body: LevelIn, ctx: OwnerOnly, session: SessionDep
) -> LevelOut:
    """Clients keep their current level (no downgrade); new thresholds apply on next visit."""
    level = await _level(session, ctx, level_id)
    before = snapshot(level)
    for key, value in body.model_dump().items():
        setattr(level, key, value)
    await session.flush()
    old, new = diff(before, snapshot(level))
    if new:
        AuditService(session).record(
            ctx.actor, "loyalty_level.update", "loyalty_level", level.id, before=old, after=new
        )
    await session.commit()
    return LevelOut.model_validate(level)


@router.delete(
    "/loyalty-levels/{level_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS
)
async def delete_level(level_id: uuid.UUID, ctx: OwnerOnly, session: SessionDep) -> None:
    """Clients on this level drop to 'no level' (FK SET NULL) until their next visit."""
    level = await _level(session, ctx, level_id)
    AuditService(session).record(
        ctx.actor, "loyalty_level.delete", "loyalty_level", level.id, before=snapshot(level)
    )
    await session.delete(level)
    await session.commit()


# ---------------- client bonuses ----------------


async def _client(session: SessionDep, ctx: AdminContext, client_id: uuid.UUID) -> Client:
    client = await session.get(Client, client_id)
    if client is None or client.branch_id != ctx.branch_id:
        raise NotFoundError("Client not found")
    return client


@router.get("/clients/{client_id}/bonus", response_model=ClientBonusOut, responses=ERRORS)
async def client_bonus(
    client_id: uuid.UUID,
    ctx: CanReadClients,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ClientBonusOut:
    client = await _client(session, ctx, client_id)
    service = BonusService(session)
    level = await session.get(LoyaltyLevel, client.level_id) if client.level_id else None
    return ClientBonusOut(
        balance=client.bonus_balance,
        ledger_balance=await BonusLedger(session).ledger_sum(client.id),
        level=level_out(level),
        visits_count=client.visits_count,
        total_spent=client.total_spent,
        transactions=[tx_out(tx) for tx in await service.history(client.id, limit)],
    )


@router.post(
    "/clients/{client_id}/bonus/adjust",
    response_model=BonusTransactionOut,
    status_code=201,
    responses=ERRORS,
)
async def adjust_bonus(
    client_id: uuid.UUID, body: AdjustIn, ctx: CanAdjust, session: SessionDep, now: NowDep
) -> BonusTransactionOut:
    """Manual credit/debit with a mandatory comment; written to the audit log."""
    await _client(session, ctx, client_id)
    tx = await BonusService(session).adjust(
        client_id, body.amount, body.comment, ctx.actor, now, body.expires_in_days
    )
    await session.commit()
    return tx_out(tx)
