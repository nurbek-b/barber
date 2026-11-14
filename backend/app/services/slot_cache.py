"""Redis cache for computed per-barber/per-day slots.

The cached value is the raw list of free starts for (barber, local date, duration) *before*
lead-time filtering and holds, so it does not depend on "now" or on who is looking.
Every change that affects a barber's availability (bookings, schedule, exceptions) bumps
`slots:ver:{barber_id}`; the version is part of the key, so stale entries are never read and
simply expire. Redis errors never break availability: we fall back to computing.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = structlog.get_logger(__name__)

CACHE_TTL_SECONDS = 60
CacheKey = tuple[uuid.UUID, date]


def _version_key(barber_id: uuid.UUID) -> str:
    return f"slots:ver:{barber_id}"


class SlotCache:
    def __init__(self, redis: Redis | None) -> None:
        self.redis = redis

    async def bump(self, barber_ids: Iterable[uuid.UUID]) -> None:
        if self.redis is None:
            return
        try:
            async with self.redis.pipeline(transaction=False) as pipe:
                for barber_id in set(barber_ids):
                    pipe.incr(_version_key(barber_id))
                await pipe.execute()
        except RedisError:
            logger.warning("slot_cache_bump_failed", exc_info=True)

    @staticmethod
    def _key(barber_id: uuid.UUID, day: date, version: str, duration: int, fingerprint: str) -> str:
        return f"slots:{barber_id}:{day.isoformat()}:{duration}:{fingerprint}:v{version}"

    async def get_many(
        self,
        items: Sequence[CacheKey],
        durations: Mapping[uuid.UUID, int],
        fingerprint: str,
    ) -> tuple[dict[CacheKey, list[datetime]], dict[uuid.UUID, str]]:
        """Return cached slots and the versions used (pass them back to `set_many`)."""
        if self.redis is None or not items:
            return {}, {}
        barber_ids = sorted({barber_id for barber_id, _ in items})
        try:
            raw_versions = await self.redis.mget([_version_key(b) for b in barber_ids])
            versions = {b: str(v or "0") for b, v in zip(barber_ids, raw_versions, strict=True)}
            keys = [self._key(b, day, versions[b], durations[b], fingerprint) for b, day in items]
            values = await self.redis.mget(keys)
        except RedisError:
            logger.warning("slot_cache_read_failed", exc_info=True)
            return {}, {}
        found: dict[CacheKey, list[datetime]] = {}
        for item, value in zip(items, values, strict=True):
            if value is not None:
                found[item] = [datetime.fromtimestamp(ts, UTC) for ts in json.loads(value)]
        return found, versions

    async def set_many(
        self,
        values: Mapping[CacheKey, list[datetime]],
        versions: Mapping[uuid.UUID, str],
        durations: Mapping[uuid.UUID, int],
        fingerprint: str,
    ) -> None:
        if self.redis is None or not values:
            return
        try:
            async with self.redis.pipeline(transaction=False) as pipe:
                for (barber_id, day), starts in values.items():
                    key = self._key(
                        barber_id,
                        day,
                        versions.get(barber_id, "0"),
                        durations[barber_id],
                        fingerprint,
                    )
                    payload = json.dumps([int(start.timestamp()) for start in starts])
                    pipe.set(key, payload, ex=CACHE_TTL_SECONDS)
                await pipe.execute()
        except RedisError:
            logger.warning("slot_cache_write_failed", exc_info=True)
