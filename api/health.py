"""Dependency health checks.

Two invariants meet in this file.

**Invariant 2 — deny by default, fail closed.** A check that raises reports `down`,
never `unknown`, and the endpoint returns 503. Reporting 200 with a shrug when the
database is unreachable is degrading open, and a health page that goes green when
it cannot tell is worse than no health page.

**Invariant 12 — log IDs and decisions, never content.** A check failure reports an
enumerated `reason` that we chose. The driver's exception message is never returned
to the caller and never logged: an asyncpg connection error carries the host, port,
user and sometimes the DSN itself.
"""
import asyncio
import logging
import time
from enum import StrEnum

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

log = logging.getLogger("ordin.health")

CHECK_TIMEOUT_SECONDS = 3.0


class CheckStatus(StrEnum):
    UP = "up"
    DOWN = "down"


class FailureReason(StrEnum):
    """The complete set of things a caller may be told. Nothing else escapes."""

    UNREACHABLE = "unreachable"
    AUTH_FAILED = "auth_failed"
    TIMEOUT = "timeout"
    ERROR = "error"


class CheckResult(BaseModel):
    name: str
    status: CheckStatus
    latency_ms: float | None = None
    reason: FailureReason | None = None


class HealthReport(BaseModel):
    status: str  # "healthy" | "unhealthy"
    version: str
    checks: list[CheckResult]

    @property
    def is_healthy(self) -> bool:
        return all(c.status is CheckStatus.UP for c in self.checks)


def _classify(exc: BaseException) -> FailureReason:
    """Map a driver exception onto one of our enumerated reasons.

    Matching is on exception type and a few stable substrings, never by passing the
    message through.
    """
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return FailureReason.TIMEOUT
    text = str(exc).lower()
    if "password" in text or "authentication" in text or "role" in text:
        return FailureReason.AUTH_FAILED
    if isinstance(exc, (ConnectionError, OSError)) or "connect" in text or "refused" in text:
        return FailureReason.UNREACHABLE
    return FailureReason.ERROR


async def check_database(engine: AsyncEngine) -> CheckResult:
    started = time.perf_counter()
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
            async with engine.connect() as conn:
                await conn.execute(sa.text("SELECT 1"))
    except BaseException as exc:  # noqa: BLE001 - fail closed on anything
        reason = _classify(exc)
        # Type only. The message can carry the DSN.
        log.warning("dependency check failed", extra={"check": "database", "reason": reason.value})
        return CheckResult(name="database", status=CheckStatus.DOWN, reason=reason)
    return CheckResult(
        name="database",
        status=CheckStatus.UP,
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
    )


async def build_report(engine: AsyncEngine, version: str) -> HealthReport:
    checks = [await check_database(engine)]
    report = HealthReport(status="healthy", version=version, checks=checks)
    report.status = "healthy" if report.is_healthy else "unhealthy"
    return report
