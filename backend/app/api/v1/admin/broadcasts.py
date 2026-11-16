"""Broadcasts to client segments (owner and admin)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import AdminContext, NowDep, SessionDep, require
from app.core.errors import ErrorResponse
from app.models import Broadcast, PromoCode
from app.schemas.admin import BroadcastIn, BroadcastOut, SegmentCountOut, SegmentIn
from app.services.branches import BranchService
from app.services.broadcasts import BroadcastService, Segment
from app.services.permissions import Perm

router = APIRouter(prefix="/broadcasts", tags=["admin-broadcasts"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

CanUse = Annotated[AdminContext, Depends(require(Perm.CLIENTS_WRITE))]


@router.post("/preview", response_model=SegmentCountOut, responses=ERRORS)
async def preview(
    body: SegmentIn, ctx: CanUse, session: SessionDep, now: NowDep
) -> SegmentCountOut:
    """How many clients would receive a broadcast to this segment."""
    salon = await BranchService(session).settings(ctx.branch_id)
    count = await BroadcastService(session).count(salon, Segment.parse(body.model_dump()), now)
    return SegmentCountOut(recipients=count)


@router.post("", response_model=BroadcastOut, status_code=201, responses=ERRORS)
async def send_broadcast(
    body: BroadcastIn, ctx: CanUse, session: SessionDep, now: NowDep
) -> BroadcastOut:
    salon = await BranchService(session).settings(ctx.branch_id)
    broadcast = await BroadcastService(session).send(
        salon,
        Segment.parse(body.segment.model_dump()),
        body.texts,
        body.promo_code_id,
        body.book_button,
        ctx.actor,
        now,
    )
    return await _out(session, broadcast)


@router.get("", response_model=list[BroadcastOut], responses=ERRORS)
async def list_broadcasts(ctx: CanUse, session: SessionDep) -> list[BroadcastOut]:
    rows = (
        (
            await session.execute(
                select(Broadcast)
                .where(Broadcast.branch_id == ctx.branch_id)
                .order_by(Broadcast.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return [await _out(session, row) for row in rows]


async def _out(session: SessionDep, broadcast: Broadcast) -> BroadcastOut:
    promo = (
        await session.get(PromoCode, broadcast.promo_code_id) if broadcast.promo_code_id else None
    )
    return BroadcastOut(
        id=broadcast.id,
        texts=broadcast.texts,
        segment=broadcast.segment,
        promo_code=promo.code if promo else None,
        recipients=broadcast.recipients,
        created_at=broadcast.created_at,
    )
