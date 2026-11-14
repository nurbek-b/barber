from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog
from app.models.base import Base
from app.models.enums import ActorType
from app.repositories.audit import AuditRepository


@dataclass(frozen=True, slots=True)
class Actor:
    """Who performs an action, plus request metadata for the audit log."""

    type: ActorType
    id: uuid.UUID | None
    ip: str | None = None
    request_id: str | None = None

    @classmethod
    def system(cls) -> Actor:
        return cls(type=ActorType.SYSTEM, id=None)


def _jsonable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


_SKIP = frozenset({"created_at", "updated_at", "password_hash"})


def snapshot(obj: Base) -> dict[str, Any]:
    """Column values of a model instance as JSON-compatible dict (secrets excluded)."""
    mapper = inspect(obj.__class__)
    return {
        attr.key: _jsonable(getattr(obj, attr.key))
        for attr in mapper.column_attrs
        if attr.key not in _SKIP
    }


def diff(before: dict[str, Any], after: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Keep only changed keys to make audit entries readable."""
    keys = {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}
    return {key: before.get(key) for key in keys}, {key: after.get(key) for key in keys}


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = AuditRepository(session)

    def record(
        self,
        actor: Actor,
        action: str,
        entity_type: str,
        entity_id: uuid.UUID | None,
        *,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        """Adds the entry to the current transaction: it commits or rolls back with the change."""
        self.repo.add(
            AuditLog(
                actor_type=actor.type,
                actor_id=actor.id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                before=_jsonable(before) if before is not None else None,
                after=_jsonable(after) if after is not None else None,
                ip=actor.ip,
                request_id=actor.request_id,
            )
        )
