"""FastAPI application factory.

Slice 1 deliberately creates no domain layer. There are no business rules yet, and
an empty `domain/` package invites someone to put a framework import in it. When
slice 2 adds entities they go in `domain/`, importing no framework, per CLAUDE.md.

This module is wiring only: configuration, logging, routing, health.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import create_async_engine

from pathlib import Path

from api.admin import router as admin_router
from api.auth import router as auth_router
from api.cases import router as cases_router
from api.config import Settings
from api.documents import router as documents_router
from api.export import router as export_router
from api.health import build_report
from api.logging import CorrelationIdMiddleware, configure_logging
from api.search import router as search_router
from api.sentinel_routes import router as sentinel_router
from api.security import SecurityMiddleware
from api.session import router as session_router
from domain.completeness import load_completeness_policy
from domain.policy import latest_policy_path, load_policy
from infra.blobstore import LocalBlobStore
from infra.crypto import EnvironmentMasterKey

log = logging.getLogger("ordin.api")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    # Before anything else. A deployment running on the template session secret starts,
    # serves traffic and looks correct, which is exactly why this raises rather than
    # warns (threat SESS-01).
    settings.refuse_unsafe_production()
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
    # Outermost of the two, so a refused request still carries the hardened headers
    # and a correlation id is never allocated for traffic that was rate-limited.
    app.add_middleware(SecurityMiddleware)
    app.state.settings = settings
    # Loaded once at startup, and deliberately NOT lazily per request: a malformed
    # policy must stop the process rather than deny every request at runtime while
    # looking like an outage (domain/policy.py raises PolicyError at load).
    policies = Path(__file__).resolve().parents[1] / "policies"
    # `latest_policy_path` rather than a literal filename: old versions stay on disk
    # so a decision recorded under them can still be explained, and the tests resolve
    # the current one through the same function, so a version bump cannot leave the
    # suite asserting against a policy nothing runs.
    app.state.policy = load_policy(latest_policy_path(policies, "case_read"))
    # Administrative capability is decided by policy too, for the same reason and
    # with the same failure mode: a bad file stops the process rather than denying
    # every request while looking like an outage.
    app.state.admin_policy = load_policy(latest_policy_path(policies, "admin"))
    # "May you declare an exception to a seal" is a separate question from "does the
    # exception count", so it is a separate policy (ADR 0029). Merging them would let
    # the rule that admits a grantee to a case also let that grantee past a seal.
    app.state.break_glass_policy = load_policy(latest_policy_path(policies, "break_glass"))
    # Procedural configuration rather than authorization, but loaded the same way
    # and for the same reason: a malformed file stops the process instead of
    # quietly reporting every case complete.
    app.state.completeness = load_completeness_policy(policies / "completeness.v1.yaml")
    # One store, constructed once. A relative root resolves against the project
    # root so the api and the worker address the same bytes without either owning
    # the path (the worker builds its own store from the same setting).
    blob_root = Path(settings.ordin_blob_root)
    if not blob_root.is_absolute():
        blob_root = Path(__file__).resolve().parents[1] / blob_root
    app.state.blobs = LocalBlobStore(
        blob_root,
        master=EnvironmentMasterKey.from_setting(
            settings.ordin_master_key.get_secret_value()
        ),
    )

    # **No OCR engine here, on purpose.** docker/python.Dockerfile gives the api image
    # no Tesseract, because an api that could run OCR invites somebody to call it
    # synchronously on a request. The upload route validates and versions; the worker
    # runs the thread (worker/intake_queue.py).

    # **A 422 must not hand the submitted value back.** FastAPI's default validation
    # response includes an `input` key holding the offending value verbatim, which for
    # this application means: the plaintext password on a short-password signup, the
    # written justification on a malformed break-glass, and the text of an extracted
    # field on a bad manual entry. Invariant 12 forbids returning document content or
    # credentials to a caller, and a value echoed in a response body also lands in
    # proxy logs, browser history and a judge's network tab.
    #
    # Registered once, for every route, rather than per-model: the leak is a property
    # of the default error shape, so anything added later inherits the fix instead of
    # having to remember it. `loc`, `msg` and `type` stay - they say WHICH field was
    # wrong and why, which is the whole point of a 422.
    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        scrubbed = [
            {k: v for k, v in error.items() if k not in ("input", "url")}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": scrubbed})

    app.include_router(admin_router)
    app.include_router(auth_router)
    app.include_router(session_router)
    app.include_router(cases_router)
    app.include_router(documents_router)
    app.include_router(export_router)
    app.include_router(search_router)
    app.include_router(sentinel_router)

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
