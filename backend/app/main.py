from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from redis.asyncio import Redis

from app.api.v1 import router as v1_router
from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_sessionmaker
from app.core.errors import install_error_handlers
from app.core.logging import NoSharedCacheMiddleware, RequestContextMiddleware, configure_logging
from app.core.media import content_type, get_media_storage
from app.core.redis import create_redis


def _operation_id(route: APIRoute) -> str:
    """Stable, unique operationIds: admin_list_barbers, miniapp_list_barbers, ..."""
    parts = route.path.split("/")  # ["", "api", "v1", "<area>", ...]
    area = parts[3] if len(parts) > 3 else "root"
    return f"{area}_{route.name}"


def create_app(settings: Settings | None = None, redis: Redis | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.validate_for_runtime()
    configure_logging(settings.log_level, settings.log_json)

    if settings.sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.env.value,
            traces_sample_rate=0.1,
            send_default_pii=False,
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.settings = settings
        app.state.engine = engine
        app.state.sessionmaker = create_sessionmaker(engine)
        app.state.redis = redis or create_redis(settings)
        try:
            yield
        finally:
            if redis is None:
                await app.state.redis.aclose()
            await engine.dispose()

    app = FastAPI(
        title="Barbershop API",
        version="1.0.0",
        lifespan=lifespan,
        generate_unique_id_function=_operation_id,
        docs_url="/api/docs" if settings.is_dev else None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    # Settings are also needed before lifespan runs (e.g. when exporting OpenAPI).
    app.state.settings = settings

    install_error_handlers(app)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "X-CSRF-Token",
                "Idempotency-Key",
                "If-Match",
                "X-Request-ID",
            ],
        )
    app.add_middleware(RequestContextMiddleware)

    app.add_middleware(NoSharedCacheMiddleware)
    app.include_router(v1_router)

    if settings.media_backend == "gcs":

        @app.get(settings.media_url_prefix + "/{key:path}", include_in_schema=False)
        async def media_object(key: str) -> Response:
            data = await get_media_storage(settings).load(key)
            if data is None:
                return Response(status_code=404, headers={"Cache-Control": "public, max-age=60"})
            return Response(
                data,
                media_type=content_type(key),
                # keys are unique per upload, so the CDN may keep them forever
                headers={"Cache-Control": "public, max-age=31536000, immutable"},
            )

    elif settings.is_dev:  # in production Nginx serves /media
        media = Path(settings.media_dir)
        media.mkdir(parents=True, exist_ok=True)
        app.mount(settings.media_url_prefix, StaticFiles(directory=media), name="media")
    return app


def app_factory() -> FastAPI:
    """Entry point: uvicorn app.main:app_factory --factory"""
    return create_app()
