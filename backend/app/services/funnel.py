"""Booking funnel: how many app sessions reached each step, per source.

The apps send one event per step and anonymous session (a random id kept in sessionStorage);
no personal data. Duplicates are ignored, so retries and back-and-forth do not inflate counts.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.slots import local_day_bounds
from app.models import FunnelEvent
from app.services.branches import BranchService

STEPS = ("open", "barber", "services", "time", "confirm", "booked")
SOURCES = ("miniapp", "web")


class FunnelService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def track(self, branch_id: uuid.UUID, session_id: str, source: str, step: str) -> None:
        await self.session.execute(
            insert(FunnelEvent)
            .values(branch_id=branch_id, session_id=session_id, source=source, step=step)
            .on_conflict_do_nothing(index_elements=["session_id", "step"])
        )
        await self.session.commit()

    async def report(
        self, branch_id: uuid.UUID, date_from: date, date_to: date
    ) -> dict[str, dict[str, int]]:
        """{source: {step: sessions}} for sessions started in the period (salon days)."""
        salon = await BranchService(self.session).settings(branch_id)
        tz = ZoneInfo(salon.timezone)
        start = local_day_bounds(date_from, tz).start
        end = local_day_bounds(date_to, tz).end
        rows = await self.session.execute(
            select(FunnelEvent.source, FunnelEvent.step, func.count())
            .where(
                FunnelEvent.branch_id == branch_id,
                FunnelEvent.created_at >= start,
                FunnelEvent.created_at < end,
            )
            .group_by(FunnelEvent.source, FunnelEvent.step)
        )
        result: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(STEPS, 0))
        for source in SOURCES:
            result[source]
        for source, step, count in rows.all():
            result[source][step] = int(count)
        return dict(result)
