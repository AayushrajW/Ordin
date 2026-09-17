"""FastAPI application factory.

Slice 1 deliberately creates no domain layer. There are no business rules yet, and
an empty `domain/` package invites someone to put a framework import in it. When
slice 2 adds entities they go in `domain/`, importing no framework, per CLAUDE.md.

This module is wiring only: configuration, logging, routing, health.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import create_async_engine

from api.config import Settings
from api.health import build_report
from api.logging import CorrelationIdMiddleware, configure_logging

log = logging.getLogger("ordin.api")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.ordin_log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # pool_pre_ping so a connection dropped while the laptop slept is
        # replaced rather than surfacing as a spurious unhealthy report.
        app.state.engine = create_async_engine(
            settings.app_dsn,
            pool_size=5,
            max_overflow=2,
            pool_pre_ping=True,
        )
        log.info(
            "api starting",
            extra={"env": settings.ordin_env, "database": settings.redacted_dsn},
        )
        try:
            yield
        finally:
            await app.state.engine.dispose()
            log.info("api stopped")

    app = FastAPI(
        title="Ordin",
        version=settings.version,
        lifespan=lifespan,
        docs_url="/docs" if settings.ordin_env == "dev" else None,
        redoc_url=None,
    )
    app.add_middleware(CorrelationIdMiddleware)
    app.state.settings = settings

    @app.get("/health")
    async def health() -> JSONResponse:
        engine = getattr(app.state, "engine", None)
        if engine is None:
            # Requested outside the lifespan (a bare ASGI test client does this).
            engine = create_async_engine(settings.app_dsn, pool_pre_ping=True)
            try:
                report = await build_report(engine, settings.version)
            finally:
                await engine.dispose()
        else:
            report = await build_report(engine, settings.version)

        # Fail closed: anything short of every dependency up is 503.
        status_code = 200 if report.is_healthy else 503
        return JSONResponse(status_code=status_code, content=report.model_dump(mode="json"))

    return app


app = create_app()
