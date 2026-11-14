from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime

from app.core.errors import ValidationAppError
from app.models import BonusTransaction, LoyaltyLevel
from app.schemas.bonus import BonusTransactionOut, LevelOut


def level_out(level: LoyaltyLevel | None) -> LevelOut | None:
    return LevelOut.model_validate(level) if level is not None else None


def tx_out(tx: BonusTransaction) -> BonusTransactionOut:
    return BonusTransactionOut.model_validate(tx)


def encode_tx_cursor(tx: BonusTransaction) -> str:
    return base64.urlsafe_b64encode(f"{tx.created_at.timestamp()}|{tx.id}".encode()).decode()


def decode_tx_cursor(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    if not cursor:
        return None
    try:
        ts, _, tx_id = base64.urlsafe_b64decode(cursor.encode()).decode().partition("|")
        return datetime.fromtimestamp(float(ts), UTC), uuid.UUID(tx_id)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationAppError("Invalid cursor", code="invalid_cursor") from exc
