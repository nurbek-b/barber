from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import MiniappContext, MiniappDep, NowDep, RedisDep, SessionDep, SlotCacheDep
from app.api.v1.availability_views import days_out, slots_out
from app.core.errors import ErrorResponse
from app.domain.slots import Interval, local_day_bounds
from app.repositories.catalog import BarberRepository
from app.schemas.schedule import AvailabilityDaysOut, AvailabilitySlotsOut
from app.services.availability import Audience, AvailabilityService
from app.services.branches import BranchService
from app.services.holds import HoldStore

router = APIRouter(prefix="/availability", tags=["miniapp-availability"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


async def _held_by_others(
    ctx: MiniappContext,
    session: AsyncSession,
    redis: Redis,
    first: date,
    last: date,
    now: datetime,
) -> dict[uuid.UUID, list[Interval]]:
    """Times other clients are confirming right now are not offered (the viewer's own hold is)."""
    salon = await BranchService(session).settings(ctx.branch_id)
    tz = ZoneInfo(salon.timezone)
    barbers, _ = await BarberRepository(session).list_page(
        ctx.branch_id, only_active=True, only_bookable=True, limit=1000
    )
    return await HoldStore(redis).busy_for(
        [b.id for b in barbers],
        local_day_bounds(first, tz).start,
        local_day_bounds(last, tz).end,
        now,
        ctx.client_id,
    )


ServiceIds = Annotated[list[uuid.UUID], Query(min_length=1, max_length=10)]


@router.get("/days", response_model=AvailabilityDaysOut, responses=ERRORS)
async def availability_days(
    ctx: MiniappDep,
    session: SessionDep,
    cache: SlotCacheDep,
    redis: RedisDep,
    now: NowDep,
    service_ids: ServiceIds,
    barber_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> AvailabilityDaysOut:
    """Free-slot counts per date (for the calendar). Without barber_id — any barber.
    Defaults: from today to the booking horizon in the salon timezone."""
    salon = await BranchService(session).settings(ctx.branch_id)
    today = now.astimezone(ZoneInfo(salon.timezone)).date()
    start = date_from or today
    end = date_to or (today + timedelta(days=salon.max_days_ahead))
    service = AvailabilityService(session, cache)
    result = await service.compute(
        ctx.branch_id,
        service_ids=service_ids,
        barber_id=barber_id,
        date_from=start,
        date_to=end,
        now=now,
        audience=Audience.CLIENT,
        extra_busy=await _held_by_others(ctx, session, redis, start, end, now),
    )
    working = await service.working_days(
        list(result.durations), [day.day for day in result.days], ZoneInfo(salon.timezone)
    )
    return days_out(result, working)


@router.get("/slots", response_model=AvailabilitySlotsOut, responses=ERRORS)
async def availability_slots(
    ctx: MiniappDep,
    session: SessionDep,
    cache: SlotCacheDep,
    redis: RedisDep,
    now: NowDep,
    service_ids: ServiceIds,
    day: Annotated[date, Query(alias="date")],
    barber_id: uuid.UUID | None = None,
) -> AvailabilitySlotsOut:
    """Free start times (UTC) on a date with the barbers available at each of them."""
    result = await AvailabilityService(session, cache).compute(
        ctx.branch_id,
        service_ids=service_ids,
        barber_id=barber_id,
        date_from=day,
        date_to=day,
        now=now,
        audience=Audience.CLIENT,
        extra_busy=await _held_by_others(ctx, session, redis, day, day, now),
    )
    return slots_out(result, day)
