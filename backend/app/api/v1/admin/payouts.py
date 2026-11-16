"""Barber payouts: what each barber earned, what was paid, what is owed (owner records)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import AdminContext, NowDep, SessionDep, require
from app.core.errors import ErrorResponse
from app.models import BarberPayout
from app.schemas.admin import PayoutBalanceOut, PayoutIn, PayoutOut
from app.services.payouts import PayoutService
from app.services.permissions import Perm

router = APIRouter(prefix="/payouts", tags=["admin-payouts"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

CanRead = Annotated[AdminContext, Depends(require(Perm.FINANCE_READ))]
CanWrite = Annotated[AdminContext, Depends(require(Perm.PAYOUTS_WRITE))]


def to_out(payout: BarberPayout, barber_name: str) -> PayoutOut:
    return PayoutOut(
        id=payout.id,
        barber_id=payout.barber_id,
        barber_name=barber_name,
        amount=payout.amount,
        paid_on=payout.paid_on,
        method=payout.method,
        note=payout.note,
        created_at=payout.created_at,
    )


@router.get("/balances", response_model=list[PayoutBalanceOut], responses=ERRORS)
async def balances(ctx: CanRead, session: SessionDep, until: date) -> list[PayoutBalanceOut]:
    rows = await PayoutService(session).balances(ctx.branch_id, until)
    return [
        PayoutBalanceOut(
            barber_id=row.barber.id,
            barber_name=row.barber.name,
            commission_bp=row.barber.commission_bp,
            earned=row.earned,
            paid=row.paid,
            due=row.due,
            last_paid_on=row.last_paid_on,
        )
        for row in rows
    ]


@router.get("", response_model=list[PayoutOut], responses=ERRORS)
async def history(
    ctx: CanRead,
    session: SessionDep,
    barber_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[PayoutOut]:
    rows = await PayoutService(session).history(ctx.branch_id, barber_id, limit)
    return [to_out(payout, name) for payout, name in rows]


@router.post("", response_model=PayoutOut, status_code=status.HTTP_201_CREATED, responses=ERRORS)
async def create(body: PayoutIn, ctx: CanWrite, session: SessionDep, now: NowDep) -> PayoutOut:
    """Record money paid to a barber; the barber gets a Telegram note if linked."""
    payout, name = await PayoutService(session).create(
        ctx.branch_id,
        barber_id=body.barber_id,
        amount=body.amount,
        paid_on=body.paid_on,
        method=body.method,
        note=body.note,
        actor=ctx.actor,
        now=now,
    )
    return to_out(payout, name)


@router.delete("/{payout_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
async def delete(payout_id: uuid.UUID, ctx: CanWrite, session: SessionDep) -> None:
    await PayoutService(session).delete(ctx.branch_id, payout_id, ctx.actor)
