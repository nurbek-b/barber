"""Signed deep links that connect a barber's Telegram chat: t.me/<bot>?start=b_<token>.

token = barber_id.hex (32) + issued_at hex (8) + HMAC-SHA256(secret)[:16] → 56 chars,
within Telegram's 64-char start parameter limit and alphabet [A-Za-z0-9_-].
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta

PREFIX = "b_"


def _sign(secret: str, body: str) -> str:
    return hmac.new(secret.encode(), f"staff-link:{body}".encode(), hashlib.sha256).hexdigest()[:16]


def make_token(barber_id: uuid.UUID, secret: str, now: datetime) -> str:
    body = f"{barber_id.hex}{int(now.timestamp()):08x}"
    return f"{PREFIX}{body}{_sign(secret, body)}"


def parse_token(token: str, secret: str, now: datetime, ttl: timedelta) -> uuid.UUID | None:
    if not token.startswith(PREFIX) or len(token) != len(PREFIX) + 56:
        return None
    raw = token.removeprefix(PREFIX)
    body, signature = raw[:40], raw[40:]
    if not hmac.compare_digest(_sign(secret, body), signature):
        return None
    try:
        barber_id = uuid.UUID(hex=body[:32])
        issued = datetime.fromtimestamp(int(body[32:], 16), UTC)
    except ValueError:
        return None
    if now - issued > ttl or issued - now > timedelta(minutes=5):
        return None
    return barber_id
