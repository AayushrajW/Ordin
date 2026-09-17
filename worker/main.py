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
