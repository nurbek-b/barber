"""'Tell me if something frees up' for fully booked days."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import MiniappDep, NowDep, SessionDep
from app.core.errors import ErrorResponse
from app.models import Barber, WaitlistEntry
from app.schemas.miniapp import WaitlistIn, WaitlistOut
from app.services.branches import BranchService
from app.services.waitlist import WaitlistService

router = APIRouter(prefix="/waitlist", tags=["miniapp-waitlist"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


async def _out(session: SessionDep, entry: WaitlistEntry) -> WaitlistOut:
    barber = await session.get(Barber, entry.barber_id) if entry.barber_id else None
    return WaitlistOut(
        id=entry.id,
        barber_id=entry.barber_id,
        barber_name=barber.name if barber else None,
        day=entry.day,
    )


@router.post("", response_model=WaitlistOut, status_code=201, responses=ERRORS)
async def join_waitlist(
    body: WaitlistIn, ctx: MiniappDep, session: SessionDep, now: NowDep
) -> WaitlistOut:
    salon = await BranchService(session).settings(ctx.branch_id)
    entry = await WaitlistService(session).join(
        ctx.identity.client,
        salon,
        barber_id=body.barber_id,
        day=body.day,
        service_ids=body.service_ids,
        now=now,
    )
    return await _out(session, entry)


@router.get("", response_model=list[WaitlistOut], responses=ERRORS)
async def my_waitlist(ctx: MiniappDep, session: SessionDep, now: NowDep) -> list[WaitlistOut]:
    salon = await BranchService(session).settings(ctx.branch_id)
    entries = await WaitlistService(session).active(ctx.identity.client, salon, now)
    return [await _out(session, entry) for entry in entries]


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
async def leave_waitlist(entry_id: uuid.UUID, ctx: MiniappDep, session: SessionDep) -> None:
    await WaitlistService(session).leave(ctx.identity.client, entry_id)
