"""Admin session cookies in two layouts.

``split`` (default, nginx / same-origin deploys)
    access_token (httpOnly, path /), refresh_token (httpOnly, path /api/v1/admin/auth),
    csrf_token (readable by JS, double-submit).

``session`` (Firebase Hosting -> Cloud Run)
    Firebase strips every cookie except ``__session`` before proxying to Cloud Run, so the
    three values are packed into that one httpOnly cookie: ``<access>~<refresh>~<csrf>``.
    JS cannot read the CSRF part; the client keeps the ``csrf_token`` returned by
    /auth/login and /auth/refresh and sends it in X-CSRF-Token, which is compared with
    the copy inside the cookie (still a double-submit: a cross-site page can read neither).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.security.tokens import (
    ACCESS_COOKIE,
    CSRF_COOKIE,
    REFRESH_COOKIE,
    REFRESH_COOKIE_PATH,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from fastapi import Response

    from app.core.config import Settings
    from app.services.admin_auth import IssuedSession

SESSION_COOKIE = "__session"
_SEP = "~"  # not in the JWT / token_urlsafe alphabets


@dataclass(frozen=True, slots=True)
class SessionTokens:
    access: str | None
    refresh: str | None
    csrf: str | None


def read_session(cookies: Mapping[str, str], settings: Settings) -> SessionTokens:
    if settings.cookie_mode == "session":
        parts = cookies.get(SESSION_COOKIE, "").split(_SEP)
        if len(parts) != 3:
            return SessionTokens(None, None, None)
        access, refresh, csrf = (p or None for p in parts)
        return SessionTokens(access, refresh, csrf)
    return SessionTokens(
        cookies.get(ACCESS_COOKIE), cookies.get(REFRESH_COOKIE), cookies.get(CSRF_COOKIE)
    )


def set_session(response: Response, issued: IssuedSession, settings: Settings) -> None:
    common = {
        "secure": settings.cookie_secure,
        "domain": settings.cookie_domain,
        "samesite": "strict",
    }
    if settings.cookie_mode == "session":
        response.set_cookie(
            SESSION_COOKIE,
            _SEP.join((issued.access_token, issued.refresh_token, issued.csrf_token)),
            max_age=settings.refresh_token_ttl_seconds,
            httponly=True,
            path="/",
            **common,  # type: ignore[arg-type]
        )
        return
    response.set_cookie(
        ACCESS_COOKIE,
        issued.access_token,
        max_age=settings.access_token_ttl_seconds,
        httponly=True,
        path="/",
        **common,  # type: ignore[arg-type]
    )
    response.set_cookie(
        REFRESH_COOKIE,
        issued.refresh_token,
        max_age=settings.refresh_token_ttl_seconds,
        httponly=True,
        path=REFRESH_COOKIE_PATH,
        **common,  # type: ignore[arg-type]
    )
    # Readable by JS: double-submit CSRF token echoed back in X-CSRF-Token.
    response.set_cookie(
        CSRF_COOKIE,
        issued.csrf_token,
        max_age=settings.refresh_token_ttl_seconds,
        httponly=False,
        path="/",
        **common,  # type: ignore[arg-type]
    )


def clear_session(response: Response, settings: Settings) -> None:
    names = (
        ((SESSION_COOKIE, "/"),)
        if settings.cookie_mode == "session"
        else ((ACCESS_COOKIE, "/"), (REFRESH_COOKIE, REFRESH_COOKIE_PATH), (CSRF_COOKIE, "/"))
    )
    for name, path in names:
        response.delete_cookie(name, path=path, domain=settings.cookie_domain)
