"""Ordin worker.

In slice 1 the worker has no jobs — the Postgres queue with `FOR UPDATE SKIP LOCKED`
arrives in slice 5a. What it has is a heartbeat, so that `/health`'s worker check says
something true rather than something decorative: a green worker means this process is
alive *and* can reach the database as ordin_app.

Note what the worker is, architecturally, because it matters later: it is the one
component that sits **outside** the authorization model. It must, in order to OCR
anything it has to read every original. The seven dimensions do not apply to it (threat
CD-01), which is why it connects as ordin_app and owns nothing, and why nothing it
persists may carry document content into a field that is read back over the API.

Configuration and logging are imported from `api/` rather than duplicated. They are
process-agnostic wiring, and a second copy drifts.
"""
import asyncio
import logging
import signal
import sys
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.config import Settings  # noqa: E402
from api.logging import configure_logging  # noqa: E402
from worker.intake_queue import process_pending  # noqa: E402

log = logging.getLogger("ordin.worker")

COMPONENT = "worker"
HEARTBEAT_INTERVAL_SECONDS = 10.0

_shutdown = asyncio.Event()


async def beat(engine) -> None:
    """Upsert this component's heartbeat. One row per component, ever."""
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO system_heartbeat (component, beat_at) "
                "VALUES (:c, now()) "
                "ON CONFLICT (component) DO UPDATE SET beat_at = now()"
            ),
            {"c": COMPONENT},
        )


async def run() -> int:
    settings = Settings()
    configure_logging(settings.ordin_log_level)

    engine = create_async_engine(settings.app_dsn, pool_size=2, pool_pre_ping=True)
    log.info(
        "worker starting",
        extra={"env": settings.ordin_env, "database": settings.redacted_dsn,
               "interval_s": HEARTBEAT_INTERVAL_SECONDS},
    )

    pipeline = _build_pipeline(settings)
    actor_id = None

    failures = 0
    try:
        while not _shutdown.is_set():
            try:
                await beat(engine)
                if failures:
                    log.info("heartbeat recovered", extra={"after_failures": failures})
                failures = 0
            except Exception as exc:  # noqa: BLE001
                failures += 1
                # Type only, never the message: a driver error carries the DSN
                # (invariant 12).
                log.warning(
                    "heartbeat failed",
                    extra={"error_type": type(exc).__name__, "consecutive": failures},
                )
            if pipeline is not None:
                try:
                    if actor_id is None:
                        actor_id = await _system_actor(engine)
                    if actor_id is not None:
                        async with engine.connect() as conn:
                            done = await process_pending(conn, pipeline, actor_id=actor_id)
                            await conn.commit()
                        if done:
                            log.info("intake batch", extra={"versions": done})
                except Exception as exc:  # noqa: BLE001
                    # Type only, never the message. A parser error can carry a
                    # fragment of the document (invariant 12, threat CD-01).
                    log.warning(
                        "intake batch failed", extra={"error_type": type(exc).__name__}
                    )

            try:
                await asyncio.wait_for(
                    _shutdown.wait(), timeout=HEARTBEAT_INTERVAL_SECONDS
                )
            except asyncio.TimeoutError:
                pass
    finally:
        await engine.dispose()
        log.info("worker stopped")
    return 0


def _build_pipeline(settings):
    """The pipeline the worker runs, or None if it cannot.

    A missing OCR engine is reported once at startup and the worker keeps its
    heartbeat, because `/health`'s worker check is about liveness and database reach.
    What it must not do is fall back to reading the PDF's own text layer and calling
    it OCR (ADR 0012).
    """
    from infra.anchor import LocalAnchorStore
    from infra.blobstore import LocalBlobStore
    from infra.esign import SimulatedESignProvider
    from infra.pipeline import Pipeline
    from infra.textsource import TesseractOcr

    blob_root = Path(settings.ordin_blob_root)
    if not blob_root.is_absolute():
        blob_root = ROOT / blob_root

    source = TesseractOcr()
    if not source.available():
        log.warning(
            "no OCR engine; uploads will queue and not be processed by this worker",
            extra={"component": COMPONENT},
        )
        return None
    return Pipeline(
        blobs=LocalBlobStore(blob_root),
        text_source=source,
        signer=SimulatedESignProvider(settings.ordin_session_secret.get_secret_value()),
        anchors=LocalAnchorStore(),
    )


async def _system_actor(engine) -> str | None:
    """Who the worker records as the actor for machine stages.

    Resolved from the database rather than invented, so every processing job names a
    real row. It is not an authorization subject: the worker sits outside the model.
    """
    async with engine.connect() as conn:
        return (
            await conn.execute(
                sa.text("SELECT id::text FROM app_user ORDER BY display_name LIMIT 1")
            )
        ).scalar_one_or_none()


def _request_shutdown(*_args) -> None:
    _shutdown.set()


def main() -> int:
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _request_shutdown)
        except (ValueError, AttributeError):
            # Not all signals exist on Windows; ctrl-c still raises KeyboardInterrupt.
            pass
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
