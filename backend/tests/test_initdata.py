from __future__ import annotations

import json
import time
from urllib.parse import parse_qsl, urlencode

import pytest

from app.core.security.initdata import (
    InitDataError,
    build_init_data,
    parse_init_data,
    parse_signed_contact,
)

TOKEN = "123456:TEST-bot-token"
TTL = 3600


def _fields(**overrides: str) -> dict[str, str]:
    fields = {
        "user": json.dumps({"id": 42, "first_name": "Айбек", "language_code": "ky"}),
        "auth_date": str(int(time.time())),
        "query_id": "AAH",
        "start_param": "ref_abc12345",
    }
    fields.update(overrides)
    return fields


def test_valid_init_data_is_parsed() -> None:
    raw = build_init_data(_fields(), TOKEN)
    data = parse_init_data(raw, TOKEN, TTL)
    assert data.user.id == 42
    assert data.user.first_name == "Айбек"
    assert data.user.language_code == "ky"
    assert data.start_param == "ref_abc12345"


def test_known_vector_from_independent_implementation() -> None:
    """Hash computed by hand with the documented algorithm (guards against refactors)."""
    import hashlib
    import hmac

    fields = _fields(auth_date="1700000000")
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    raw = urlencode({**fields, "hash": expected})
    assert parse_init_data(raw, TOKEN, 10**10, now=1700000001).auth_date == 1700000000


def test_tampered_field_is_rejected() -> None:
    raw = build_init_data(_fields(), TOKEN)
    pairs = dict(parse_qsl(raw))
    pairs["user"] = json.dumps({"id": 1, "first_name": "Hacker"})
    with pytest.raises(InitDataError, match="signature"):
        parse_init_data(urlencode(pairs), TOKEN, TTL)


def test_wrong_bot_token_is_rejected() -> None:
    raw = build_init_data(_fields(), "999:other")
    with pytest.raises(InitDataError, match="signature"):
        parse_init_data(raw, TOKEN, TTL)


def test_expired_init_data_is_rejected() -> None:
    old = str(int(time.time()) - TTL - 5)
    raw = build_init_data(_fields(auth_date=old), TOKEN)
    with pytest.raises(InitDataError, match="expired"):
        parse_init_data(raw, TOKEN, TTL)


def test_future_auth_date_is_rejected() -> None:
    future = str(int(time.time()) + 3600)
    raw = build_init_data(_fields(auth_date=future), TOKEN)
    with pytest.raises(InitDataError, match="future"):
        parse_init_data(raw, TOKEN, TTL)


@pytest.mark.parametrize(
    "raw",
    ["", "garbage", "auth_date=1&user=%7B%7D", "a=1&a=2&hash=x"],
)
def test_malformed_init_data(raw: str) -> None:
    with pytest.raises(InitDataError):
        parse_init_data(raw, TOKEN, TTL)


def test_missing_user_is_rejected() -> None:
    fields = _fields()
    del fields["user"]
    with pytest.raises(InitDataError, match="user"):
        parse_init_data(build_init_data(fields, TOKEN), TOKEN, TTL)


def test_empty_bot_token_never_validates() -> None:
    raw = build_init_data(_fields(), "")
    with pytest.raises(InitDataError, match="not configured"):
        parse_init_data(raw, "", TTL)


def test_signed_contact() -> None:
    contact = json.dumps({"user_id": 42, "phone_number": "996555123456", "first_name": "A"})
    raw = build_init_data({"contact": contact, "auth_date": str(int(time.time()))}, TOKEN)
    parsed = parse_signed_contact(raw, TOKEN, TTL)
    assert parsed.user_id == 42
    assert parsed.phone_number == "996555123456"


def test_signed_contact_tampered_phone() -> None:
    contact = json.dumps({"user_id": 42, "phone_number": "996555123456"})
    raw = build_init_data({"contact": contact, "auth_date": str(int(time.time()))}, TOKEN)
    pairs = dict(parse_qsl(raw))
    pairs["contact"] = json.dumps({"user_id": 42, "phone_number": "996700000000"})
    with pytest.raises(InitDataError):
        parse_signed_contact(urlencode(pairs), TOKEN, TTL)
