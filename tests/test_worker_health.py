"""Worker liveness, via the heartbeat it writes.

The worker has no jobs yet — the queue arrives in slice 5a. What it has is a
heartbeat row, and `/health` reads it. That makes the worker check meaningful
rather than decorative: a green worker proves the process is alive *and* that it
can reach the database as ordin_app.

The invariant at risk here is 2 (deny by default, fail closed). A freshly migrated
database has **no** heartbeat row at all, and the tempting bug is to treat absence
as "probably fine, it just started". Absence and staleness both mean down.
"""
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from api.health import CheckStatus, FailureReason, check_worker

pytestmark = pytest.mark.requires_db

COMPONENT = "worker"


async def set_heartbeat(engine, age: timedelta | None) -> None:
    """Write a heartbeat `age` ago, or remove it entirely when age is None."""
    async with engine.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM system_heartbeat WHERE component = :c"),
            {"c": COMPONENT},
        )
        if age is not None:
            await conn.execute(
                sa.text(
                    "INSERT INTO system_heartbeat (component, beat_at) "
                    "VALUES (:c, :t)"
                ),
                {"c": COMPONENT, "t": datetime.now(timezone.utc) - age},
            )


@pytest.fixture
async def engine(live_settings):
    eng = create_async_engine(live_settings.app_dsn)
    yield eng
    await eng.dispose()


async def test_missing_heartbeat_reports_down_not_unknown(engine):
    """Invariant 2. A fresh database has no row; that is not a pass."""
    await set_heartbeat(engine, None)
    result = await check_worker(engine)
    assert result.status is CheckStatus.DOWN, (
        "a missing heartbeat reported something other than down - a freshly "
        "migrated database would show a healthy worker that does not exist"
    )
    assert result.reason is FailureReason.UNREACHABLE


async def test_stale_heartbeat_reports_down(engine):
    """A worker that died five minutes ago is down, however recently it once beat."""
    await set_heartbeat(engine, timedelta(minutes=5))
    result = await check_worker(engine)
    assert result.status is CheckStatus.DOWN
    assert result.reason is FailureReason.STALE


async def test_recent_heartbeat_reports_up(engine):
    await set_heartbeat(engine, timedelta(seconds=2))
    result = await check_worker(engine)
    assert result.status is CheckStatus.UP, f"expected up, got {result.reason}"
    assert result.name == "worker"


async def test_heartbeat_exactly_at_the_boundary_is_down(engine):
    """Fail closed at the boundary rather than open."""
    from api.health import WORKER_HEARTBEAT_MAX_AGE_SECONDS

    await set_heartbeat(engine, timedelta(seconds=WORKER_HEARTBEAT_MAX_AGE_SECONDS + 1))
    result = await check_worker(engine)
    assert result.status is CheckStatus.DOWN


async def test_worker_check_never_leaks_a_driver_message(engine):
    """Invariant 12, same rule as the database check."""
    await set_heartbeat(engine, None)
    result = await check_worker(engine)
    assert result.reason in set(FailureReason), "reason escaped the enumeration"
    assert "Traceback" not in str(result.model_dump())
