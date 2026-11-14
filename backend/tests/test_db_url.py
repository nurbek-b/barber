from app.core.db import normalize_database_url


def test_plain_asyncpg_url_is_untouched() -> None:
    url, args = normalize_database_url("postgresql+asyncpg://u:p@localhost:5432/db")
    assert url == "postgresql+asyncpg://u:p@localhost:5432/db"
    assert args == {}


def test_neon_direct_url() -> None:
    url, args = normalize_database_url(
        "postgresql://u:p@ep-cool-1.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    )
    assert url == "postgresql+asyncpg://u:p@ep-cool-1.eu-central-1.aws.neon.tech/neondb"
    assert args == {"ssl": "require"}


def test_neon_pooler_disables_statement_cache() -> None:
    url, args = normalize_database_url(
        "postgres://u:p@ep-cool-1-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=verify-full"
    )
    assert url.startswith("postgresql+asyncpg://")
    assert url.endswith("?prepared_statement_cache_size=0")
    assert args["ssl"] is True
    assert args["statement_cache_size"] == 0
    first, second = args["prepared_statement_name_func"](), args["prepared_statement_name_func"]()
    assert first != second
