from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.core.config import get_settings
from app.core.db import normalize_database_url
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def database_url() -> str:
    """alembic.ini url (tests) > DATABASE_URL_DIRECT (bypasses PgBouncer) > DATABASE_URL."""
    explicit = config.get_main_option("sqlalchemy.url")
    if explicit:
        return explicit
    settings = get_settings()
    return settings.database_url_direct or settings.database_url


target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=normalize_database_url(database_url())[0],
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    url, connect_args = normalize_database_url(database_url())
    connectable = create_async_engine(url, poolclass=pool.NullPool, connect_args=connect_args)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:  # called programmatically (tests) with an open connection
        do_run_migrations(connection)
        return
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
