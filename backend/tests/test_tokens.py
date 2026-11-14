from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.security.passwords import hash_password, verify_password
from app.core.security.tokens import (
    TokenError,
    create_access_token,
    csrf_matches,
    decode_access_token,
)

SECRET = "s" * 40


def _token(**overrides: object) -> str:
    params: dict[str, object] = {
        "admin_user_id": uuid.uuid4(),
        "role": "admin",
        "session_family": uuid.uuid4(),
        "secret": SECRET,
        "algorithm": "HS256",
        "ttl_seconds": 60,
    }
    params.update(overrides)
    return create_access_token(**params)  # type: ignore[arg-type]


def test_access_token_roundtrip() -> None:
    admin_id = uuid.uuid4()
    claims = decode_access_token(_token(admin_user_id=admin_id), secret=SECRET, algorithm="HS256")
    assert claims.admin_user_id == admin_id
    assert claims.role == "admin"


def test_expired_token() -> None:
    token = _token(now=datetime.now(UTC) - timedelta(hours=1))
    with pytest.raises(TokenError):
        decode_access_token(token, secret=SECRET, algorithm="HS256")


def test_wrong_secret() -> None:
    with pytest.raises(TokenError):
        decode_access_token(_token(), secret="x" * 40, algorithm="HS256")


def test_alg_none_is_rejected() -> None:
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "typ": "access", "iat": 0, "exp": 9999999999},
        key="",
        algorithm="none",
    )
    with pytest.raises(TokenError):
        decode_access_token(forged, secret=SECRET, algorithm="HS256")


def test_wrong_type() -> None:
    now = int(datetime.now(UTC).timestamp())
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "typ": "refresh", "iat": now, "exp": now + 60},
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(TokenError, match="type"):
        decode_access_token(token, secret=SECRET, algorithm="HS256")


def test_csrf_matches() -> None:
    assert csrf_matches("abc", "abc")
    assert not csrf_matches("abc", "abd")
    assert not csrf_matches(None, "abc")
    assert not csrf_matches("abc", None)


def test_password_hashing() -> None:
    hashed = hash_password("secret-password")
    assert verify_password(hashed, "secret-password")
    assert not verify_password(hashed, "wrong")
    assert not verify_password(None, "secret-password")
