"""Temporary slot holds in Redis (UX layer; the DB exclusion constraint is the real guard).

Layout
------
holds:{barber_id}   ZSET  member = "{hold_id}|{client_id}|{start_ts}|{until_ts}|{expires_ts}",
                          score  = start_ts (seconds)
hold:{hold_id}      STRING JSON with the full hold (services, prices are recomputed on booking)
client_hold:{cid}   STRING "{barber_id}|{member}" — one active hold per client

Placing a hold is one Lua script: it drops expired members and the client's own previous hold
on this barber, checks overlap with other clients' holds and inserts — atomically.
"""

from __future__ import annotations

import json
import secrets
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.domain.slots import Interval

logger = structlog.get_logger(__name__)

HOLD_TTL = timedelta(minutes=5)

_PLACE = """
local zkey, hkey, ckey = KEYS[1], KEYS[2], KEYS[3]
local member, start_ts, until_ts = ARGV[1], tonumber(ARGV[2]), tonumber(ARGV[3])
local now_ts, client, payload, ttl = tonumber(ARGV[4]), ARGV[5], ARGV[6], tonumber(ARGV[7])

local candidates = redis.call('ZRANGEBYSCORE', zkey, '-inf', '(' .. until_ts)
for _, other in ipairs(candidates) do
  local parts = {}
  for piece in string.gmatch(other, '([^|]+)') do table.insert(parts, piece) end
  local other_client, other_until, other_exp = parts[2], tonumber(parts[4]), tonumber(parts[5])
  if other_exp <= now_ts or other_client == client then
    redis.call('ZREM', zkey, other)
  elseif other_until > start_ts then
    return 0
  end
end
redis.call('ZADD', zkey, start_ts, member)
redis.call('EXPIRE', zkey, ttl * 4)
redis.call('SET', hkey, payload, 'EX', ttl)
redis.call('SET', ckey, ARGV[8], 'EX', ttl)
return 1
"""


@dataclass(frozen=True, slots=True)
class Hold:
    id: str
    client_id: uuid.UUID
    barber_id: uuid.UUID
    service_ids: tuple[uuid.UUID, ...]
    start_at: datetime
    end_at: datetime
    blocked_until: datetime
    expires_at: datetime

    def to_json(self) -> str:
        return json.dumps(
            {
                "id": self.id,
                "client_id": str(self.client_id),
                "barber_id": str(self.barber_id),
                "service_ids": [str(item) for item in self.service_ids],
                "start_at": int(self.start_at.timestamp()),
                "end_at": int(self.end_at.timestamp()),
                "blocked_until": int(self.blocked_until.timestamp()),
                "expires_at": int(self.expires_at.timestamp()),
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> Hold:
        data = json.loads(raw)

        def ts(key: str) -> datetime:
            return datetime.fromtimestamp(int(data[key]), UTC)

        return cls(
            id=str(data["id"]),
            client_id=uuid.UUID(data["client_id"]),
            barber_id=uuid.UUID(data["barber_id"]),
            service_ids=tuple(uuid.UUID(item) for item in data["service_ids"]),
            start_at=ts("start_at"),
            end_at=ts("end_at"),
            blocked_until=ts("blocked_until"),
            expires_at=ts("expires_at"),
        )

    @property
    def member(self) -> str:
        return "|".join(
            (
                self.id,
                str(self.client_id),
                str(int(self.start_at.timestamp())),
                str(int(self.blocked_until.timestamp())),
                str(int(self.expires_at.timestamp())),
            )
        )


class HoldUnavailableError(Exception):
    """Redis is down: holds are a UX feature, callers may continue without them."""


class HoldStore:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    @staticmethod
    def new_id() -> str:
        return secrets.token_urlsafe(12)

    async def place(self, hold: Hold, now: datetime) -> bool:
        """True if placed; False if it overlaps another client's active hold."""
        try:
            previous = await self.redis.get(f"client_hold:{hold.client_id}")
            if previous:
                old_barber, _, old_member = str(previous).partition("|")
                await self.redis.zrem(f"holds:{old_barber}", old_member)
                await self.redis.delete(f"hold:{old_member.split('|', 1)[0]}")
            result = await self.redis.eval(  # type: ignore[misc]
                _PLACE,
                3,
                f"holds:{hold.barber_id}",
                f"hold:{hold.id}",
                f"client_hold:{hold.client_id}",
                hold.member,
                str(int(hold.start_at.timestamp())),
                str(int(hold.blocked_until.timestamp())),
                str(int(now.timestamp())),
                str(hold.client_id),
                hold.to_json(),
                str(int(HOLD_TTL.total_seconds())),
                f"{hold.barber_id}|{hold.member}",
            )
        except RedisError as exc:
            logger.warning("hold_place_failed", exc_info=True)
            raise HoldUnavailableError from exc
        return bool(result)

    async def get(self, hold_id: str) -> Hold | None:
        try:
            raw = await self.redis.get(f"hold:{hold_id}")
        except RedisError as exc:
            raise HoldUnavailableError from exc
        return Hold.from_json(str(raw)) if raw else None

    async def release(self, hold: Hold) -> None:
        try:
            await self.redis.zrem(f"holds:{hold.barber_id}", hold.member)
            await self.redis.delete(f"hold:{hold.id}")
            current = await self.redis.get(f"client_hold:{hold.client_id}")
            if current and str(current).endswith(hold.member):
                await self.redis.delete(f"client_hold:{hold.client_id}")
        except RedisError:
            logger.warning("hold_release_failed", exc_info=True)

    async def busy_for(
        self,
        barber_ids: Iterable[uuid.UUID],
        start: datetime,
        end: datetime,
        now: datetime,
        exclude_client: uuid.UUID | None,
    ) -> dict[uuid.UUID, list[Interval]]:
        """Active holds of *other* clients as busy intervals. Never raises."""
        ids: Sequence[uuid.UUID] = list(barber_ids)
        result: dict[uuid.UUID, list[Interval]] = {}
        if not ids:
            return result
        try:
            async with self.redis.pipeline(transaction=False) as pipe:
                for barber_id in ids:
                    # members starting before `end`; long ones starting earlier are rare (<1 day)
                    pipe.zrangebyscore(
                        f"holds:{barber_id}",
                        int((start - timedelta(days=1)).timestamp()),
                        f"({int(end.timestamp())}",
                    )
                rows = await pipe.execute()
        except RedisError:
            logger.warning("hold_read_failed", exc_info=True)
            return result
        now_ts = int(now.timestamp())
        for barber_id, members in zip(ids, rows, strict=True):
            for member in members:
                _, client, start_ts, until_ts, expires_ts = str(member).split("|")
                if int(expires_ts) <= now_ts:
                    continue
                if exclude_client is not None and client == str(exclude_client):
                    continue
                interval = Interval(
                    datetime.fromtimestamp(int(start_ts), UTC),
                    datetime.fromtimestamp(int(until_ts), UTC),
                )
                if interval.end > start:
                    result.setdefault(barber_id, []).append(interval)
        return result
