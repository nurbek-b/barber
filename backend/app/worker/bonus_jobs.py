"""Periodic bonus jobs. All are idempotent and safe to run hourly or after downtime:
expiry burns only what is still unburned, birthday credits are keyed per year, warnings
per client per day."""

from __future__ import annotations

from datetime import datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.bonus import BonusService

logger = structlog.get_logger(__name__)


async def run_bonus_jobs(maker: async_sessionmaker[AsyncSession], now: datetime) -> dict[str, int]:
    result: dict[str, int] = {}
    for name in ("expire", "birthdays", "warnings"):
        async with maker() as session:
            service = BonusService(session)
            if name == "expire":
                result[name] = await service.expire_due(now)
            elif name == "birthdays":
                result[name] = await service.birthdays(now)
            else:
                result[name] = await service.warn_expiring(now)
            await session.commit()
    if any(result.values()):
        logger.info("bonus_jobs", **result)
    return result
