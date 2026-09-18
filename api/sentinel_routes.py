"""Slice 8: the Sentinel scenarios over HTTP, for the dashboard page.

**It runs the scenarios; it does not report stored ones.** A dashboard that renders
the last saved run can show green from an hour ago, and a check that cannot currently
fail is worse than no check — the registry's own docstring says so. Every request here
executes the scenarios against the live application and returns what happened, with
the timestamp it happened at.

Two consequences of that, both deliberate:

  It is a POST. The scenarios establish their own preconditions — redacting a
  specimen, pushing a fixture through the pipeline — so this writes, and a GET that
  writes is a lie to every cache and crawler between here and the browser.

  It is restricted to the dev environment and requires a session. Scenarios exercise
  authorization boundaries by design; a diagnostic that runs privileged checks should
  not be a route an unauthenticated caller can reach, and in a deployment it should
  not be a route at all. That restriction is a guard, not a claim — see ADR 0015 for
  what it is and is not worth.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.deps import require_subject
from domain.subject import Subject
from sentinel.context import load_ids, load_scenarios
from sentinel.registry import Outcome, run_all

log = logging.getLogger("ordin.api.sentinel")

router = APIRouter(tags=["sentinel"])


class ScenarioResultOut(BaseModel):
    id: str
    invariant: str
    setup: str
    expected: str
    actual: str
    severity: str
    slice_id: str
    outcome: str


class SentinelRunOut(BaseModel):
    ran_at: datetime
    passing: int
    total: int
    results: list[ScenarioResultOut]


class _Ctx:
    """What a scenario receives. Matches the CLI runner's context exactly."""

    def __init__(self, client, engine, ids, blobs):
        self.client = client
        self.engine = engine
        self.ids = ids
        self.blobs = blobs


@router.post("/sentinel/run")
async def run_sentinel(
    request: Request, subject: Subject = Depends(require_subject)
) -> SentinelRunOut:
    # Importing registers the scenarios. Done here rather than at module import so a
    # scenario file with an error cannot stop the API from starting — Sentinel is an
    # instrument, and an instrument must not be able to take down what it measures.
    load_scenarios()

    if request.app.state.settings.ordin_env != "dev":
        raise HTTPException(status_code=404, detail="not_found")

    # Imported here, not at module scope. Sentinel is an instrument, and an instrument
    # must not be able to take down what it measures: a missing client should disable
    # the dashboard, not stop the api from starting. It did exactly that once, in the
    # container, because httpx was a dev-only dependency.
    try:
        import httpx
    except ImportError:
        raise HTTPException(status_code=503, detail="scenario_runner_unavailable")

    engine = request.app.state.engine
    async with engine.connect() as conn:
        ids = await load_ids(conn)
    # The connection is released before the scenarios run. They make their own
    # requests into this same application, and holding one here while they compete
    # for a five-connection pool is a deadlock waiting for a demo.

    transport = httpx.ASGITransport(app=request.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://sentinel") as client:
        results = await run_all(
            _Ctx(client=client, engine=engine, ids=ids, blobs=request.app.state.blobs)
        )

    log.info(
        "sentinel run",
        extra={
            "scenarios": len(results),
            "failing": sum(1 for r in results if not r.ok),
            "actor": subject.user_id,
        },
    )
    return SentinelRunOut(
        ran_at=datetime.now(timezone.utc),
        passing=sum(1 for r in results if r.outcome is Outcome.PASS),
        total=len(results),
        results=[
            ScenarioResultOut(
                id=r.id,
                invariant=r.invariant,
                setup=r.setup,
                expected=r.expected,
                actual=r.actual,
                severity=r.severity.value,
                slice_id=r.slice_id,
                outcome=r.outcome.value,
            )
            for r in results
        ],
    )
