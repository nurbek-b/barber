from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings

# libpq-only query parameters that asyncpg does not accept as keyword arguments
_LIBPQ_ONLY = {"sslmode", "channel_binding", "sslrootcert", "options"}


def normalize_database_url(url: str) -> tuple[str, dict[str, Any]]:
    """Turn a libpq-style URL (as Neon prints it) into an asyncpg URL + connect_args.

    * ``postgres://`` / ``postgresql://`` -> ``postgresql+asyncpg://``
    * ``sslmode=require`` -> ``ssl="require"``; ``verify-ca`` / ``verify-full`` -> verified TLS
    * a PgBouncer host (Neon ``-pooler``) runs in transaction mode, so asyncpg's prepared
      statement caches are disabled and statement names are made unique.
    """
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in {"postgres", "postgresql"}:
        scheme = "postgresql+asyncpg"
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    connect_args: dict[str, Any] = {}

    sslmode = query.get("sslmode", "")
    if sslmode in {"require", "prefer", "allow"}:
        connect_args["ssl"] = "require" if sslmode == "require" else sslmode
    elif sslmode in {"verify-ca", "verify-full"}:
        connect_args["ssl"] = True
    elif sslmode == "disable":
        connect_args["ssl"] = False
    for key in _LIBPQ_ONLY:
        query.pop(key, None)

    if "-pooler." in (parts.hostname or "") or query.pop("pgbouncer", "") == "true":
        query["prepared_statement_cache_size"] = "0"
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_name_func"] = lambda: f"__asyncpg_{uuid4().hex}__"

    clean = urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    return clean, connect_args


def create_engine(settings: Settings, url: str | None = None) -> AsyncEngine:
    clean, connect_args = normalize_database_url(url or settings.database_url)
    return create_async_engine(
        clean,
        pool_size=settings.database_pool_size,
        pool_pre_ping=True,
        pool_recycle=300,  # serverless Postgres closes idle connections
        echo=settings.database_echo,
        connect_args=connect_args,
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def session_scope(
    maker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """One session per request. Services own commit; anything uncommitted is rolled back."""
    async with maker() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise
