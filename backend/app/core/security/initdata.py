"""Telegram Mini App initData validation.

https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
hash       = hex(HMAC_SHA256(key=secret_key, msg=data_check_string))
data_check_string = "\n".join(sorted(f"{k}={v}" for k, v in fields if k != "hash"))

The same algorithm validates the signed contact returned by requestContact().
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode


class InitDataError(Exception):
    """initData is malformed, has a bad signature or is expired."""


@dataclass(frozen=True, slots=True)
class TelegramUser:
    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    photo_url: str | None = None
    is_premium: bool = False


@dataclass(frozen=True, slots=True)
class InitData:
    user: TelegramUser
    auth_date: int
    start_param: str | None
    query_id: str | None
    raw: dict[str, str]


def _secret_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def _data_check_string(fields: dict[str, str]) -> str:
    return "\n".join(f"{key}={fields[key]}" for key in sorted(fields) if key != "hash")


def sign_fields(fields: dict[str, str], bot_token: str) -> str:
    """Compute the hash for the given fields. Used by tests and the dev mock environment."""
    return hmac.new(
        _secret_key(bot_token), _data_check_string(fields).encode(), hashlib.sha256
    ).hexdigest()


def build_init_data(fields: dict[str, str], bot_token: str) -> str:
    """Build a signed initData query string (for tests and dev mode)."""
    signed = {**fields, "hash": sign_fields(fields, bot_token)}
    return urlencode(signed)


def verify_signed_query(
    raw: str, bot_token: str, ttl_seconds: int, now: int | None = None
) -> dict[str, str]:
    """Validate the signature and auth_date; return the decoded fields."""
    if not bot_token:
        raise InitDataError("bot token is not configured")
    if not raw or len(raw) > 8192:
        raise InitDataError("empty or oversized init data")
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise InitDataError("malformed init data") from exc

    fields: dict[str, str] = {}
    for key, value in pairs:
        if key in fields:
            raise InitDataError(f"duplicate key: {key}")
        fields[key] = value

    received_hash = fields.get("hash")
    if not received_hash:
        raise InitDataError("hash is missing")

    expected = sign_fields(fields, bot_token)
    if not hmac.compare_digest(expected, received_hash):
        raise InitDataError("invalid signature")

    try:
        auth_date = int(fields["auth_date"])
    except (KeyError, ValueError) as exc:
        raise InitDataError("auth_date is missing or invalid") from exc

    current = int(time.time()) if now is None else now
    if auth_date > current + 60:
        raise InitDataError("auth_date is in the future")
    if current - auth_date > ttl_seconds:
        raise InitDataError("init data expired")
    return fields


def _parse_user(raw_user: str) -> TelegramUser:
    try:
        data: Any = json.loads(raw_user)
    except json.JSONDecodeError as exc:
        raise InitDataError("user is not valid JSON") from exc
    if not isinstance(data, dict) or not isinstance(data.get("id"), int):
        raise InitDataError("user.id is missing")
    return TelegramUser(
        id=data["id"],
        first_name=str(data.get("first_name") or ""),
        last_name=data.get("last_name"),
        username=data.get("username"),
        language_code=data.get("language_code"),
        photo_url=data.get("photo_url"),
        is_premium=bool(data.get("is_premium", False)),
    )


def parse_init_data(raw: str, bot_token: str, ttl_seconds: int, now: int | None = None) -> InitData:
    fields = verify_signed_query(raw, bot_token, ttl_seconds, now)
    raw_user = fields.get("user")
    if not raw_user:
        raise InitDataError("user is missing")
    return InitData(
        user=_parse_user(raw_user),
        auth_date=int(fields["auth_date"]),
        start_param=fields.get("start_param") or None,
        query_id=fields.get("query_id") or None,
        raw=fields,
    )


@dataclass(frozen=True, slots=True)
class SignedContact:
    user_id: int
    phone_number: str
    first_name: str
    last_name: str | None


def parse_signed_contact(
    raw: str, bot_token: str, ttl_seconds: int, now: int | None = None
) -> SignedContact:
    """Validate the `contact=...&auth_date=...&hash=...` string from requestContact()."""
    fields = verify_signed_query(raw, bot_token, ttl_seconds, now)
    try:
        contact: Any = json.loads(fields["contact"])
    except (KeyError, json.JSONDecodeError) as exc:
        raise InitDataError("contact is missing") from exc
    if not isinstance(contact, dict) or not contact.get("phone_number"):
        raise InitDataError("contact.phone_number is missing")
    return SignedContact(
        user_id=int(contact["user_id"]),
        phone_number=str(contact["phone_number"]),
        first_name=str(contact.get("first_name") or ""),
        last_name=contact.get("last_name"),
    )
