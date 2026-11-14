from __future__ import annotations

import time

from redis.asyncio import Redis

from app.core.config import Settings


def create_redis(settings: Settings) -> Redis:
    redis: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return redis


async def hit_rate_limit(redis: Redis, key: str, limit: int, window_seconds: int) -> bool:
    """Sliding-window limiter. Returns True when the call is over the limit."""
    now_ms = int(time.time() * 1000)
    window_start = now_ms - window_seconds * 1000
    redis_key = f"rl:{key}"
    async with redis.pipeline(transaction=True) as pipe:
        pipe.zremrangebyscore(redis_key, 0, window_start)
        pipe.zadd(redis_key, {f"{now_ms}:{time.perf_counter_ns()}": now_ms})
        pipe.zcard(redis_key)
        pipe.expire(redis_key, window_seconds)
        results = await pipe.execute()
    count = int(results[2])
    return count > limit
