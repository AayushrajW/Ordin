"""Ordin Sentinel — the scenario registry.

`docs/PLAN.md` R7 changed Sentinel from a late slice into a registry opened early,
with each slice contributing its own scenarios as it lands. The reasoning: Sentinel is
the thing that converts a security claim from an assertion into a green tick a judge
can watch turn red, and a late slice is the one that does not get built. Contributing
one scenario per slice costs minutes; building eight at hour 28 does not happen.

**A scenario is not a unit test.** A unit test asks "does this function behave?" A
scenario asks "is this invariant still true of the running system?", names the
invariant, and records enough to be read by someone who did not write it: what was set
up, what was expected, what actually happened, and how bad it is if it fails.

The honesty rule that applies here: a scenario that cannot currently fail is worse
than no scenario, because it manufactures confidence. `run_all` reports scenarios that
raised separately from scenarios that failed, so an error is never quietly a pass.
"""
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Awaitable, Callable


class Severity(StrEnum):
    CRITICAL = "critical"   # a protected identity is disclosed
    HIGH = "high"           # authorization bypassed, no direct disclosure yet
    MEDIUM = "medium"       # weakens a control or leaks metadata


class Outcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"         # the scenario itself broke; NOT a pass


@dataclass(frozen=True)
class Scenario:
    id: str
    invariant: str
    setup: str
    expected: str
    severity: Severity
    slice_id: str
    run: Callable[..., Awaitable[str]]
    """Returns a description of what actually happened. Raises AssertionError to fail."""


@dataclass(frozen=True)
class ScenarioResult:
    id: str
    invariant: str
    setup: str
    expected: str
    actual: str
    severity: Severity
    slice_id: str
    outcome: Outcome
    at: datetime

    @property
    def ok(self) -> bool:
        return self.outcome is Outcome.PASS


REGISTRY: list[Scenario] = []


def scenario(
    *, id: str, invariant: str, setup: str, expected: str, severity: Severity, slice_id: str
):
    """Register a scenario. Import the module and it is registered."""

    def decorate(fn: Callable[..., Awaitable[str]]) -> Callable[..., Awaitable[str]]:
        if any(s.id == id for s in REGISTRY):
            raise ValueError(f"duplicate scenario id {id!r}")
        REGISTRY.append(
            Scenario(
                id=id,
                invariant=invariant,
                setup=setup,
                expected=expected,
                severity=severity,
                slice_id=slice_id,
                run=fn,
            )
        )
        return fn

    return decorate


async def run_all(ctx, *, now: datetime | None = None) -> list[ScenarioResult]:
    """Run every registered scenario. An exception is ERROR, never PASS."""
    at = now or datetime.now(timezone.utc)
    results: list[ScenarioResult] = []
    for item in REGISTRY:
        try:
            actual = await item.run(ctx)
            outcome = Outcome.PASS
        except AssertionError as exc:
            actual = str(exc) or "assertion failed"
            outcome = Outcome.FAIL
        except Exception as exc:  # noqa: BLE001
            # Deliberately distinct from FAIL. A scenario that errored proved nothing,
            # and reporting it as a pass is how a dashboard lies.
            actual = f"scenario raised {type(exc).__name__}: {exc}"
            outcome = Outcome.ERROR
            traceback.clear_frames(exc.__traceback__) if exc.__traceback__ else None
        results.append(
            ScenarioResult(
                id=item.id,
                invariant=item.invariant,
                setup=item.setup,
                expected=item.expected,
                actual=actual,
                severity=item.severity,
                slice_id=item.slice_id,
                outcome=outcome,
                at=at,
            )
        )
    return results
