"""JWT access tokens, opaque refresh tokens and CSRF tokens for the admin panel."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"
REFRESH_COOKIE_PATH = "/api/v1/admin/auth"


class TokenError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class AccessClaims:
    admin_user_id: uuid.UUID
    role: str
    session_family: uuid.UUID


def create_access_token(
    *,
    admin_user_id: uuid.UUID,
    role: str,
    session_family: uuid.UUID,
    secret: str,
    algorithm: str,
    ttl_seconds: int,
    now: datetime | None = None,
) -> str:
    issued = now or datetime.now(UTC)
    payload = {
        "sub": str(admin_user_id),
        "role": role,
        "fam": str(session_family),
        "typ": "access",
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(seconds=ttl_seconds)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_access_token(token: str, *, secret: str, algorithm: str) -> AccessClaims:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[algorithm],
            options={"require": ["sub", "exp", "iat", "typ"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if payload.get("typ") != "access":
        raise TokenError("wrong token type")
    try:
        return AccessClaims(
            admin_user_id=uuid.UUID(payload["sub"]),
            role=str(payload["role"]),
            session_family=uuid.UUID(payload["fam"]),
        )
    except (KeyError, ValueError) as exc:
        raise TokenError("malformed claims") from exc


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_matches(cookie_value: str | None, header_value: str | None) -> bool:
    if not cookie_value or not header_value:
        return False
    return secrets.compare_digest(cookie_value, header_value)
