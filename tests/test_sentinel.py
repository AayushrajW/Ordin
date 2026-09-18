"""Sentinel runs, and its scenarios can actually fail.

Two things are being checked, and the second matters more.

  1. Every registered scenario passes against the running system.
  2. A scenario that should fail **does** fail, and an errored scenario is reported
     as ERROR rather than PASS.

Without (2), a dashboard of green ticks is theatre - and this project's whole pitch
is that its security claims are demonstrable rather than asserted. A scenario harness
that cannot go red is the most expensive kind of self-deception, because it is the
thing you point at when challenged.
"""
from dataclasses import dataclass

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from api.main import create_app
from sentinel.context import load_ids, load_scenarios
from sentinel.registry import REGISTRY, Outcome, Severity, run_all, scenario

pytestmark = pytest.mark.requires_db


@dataclass
class Ctx:
    client: httpx.AsyncClient
    engine: object
    ids: dict
    # Scenarios that push a document through the pipeline need somewhere to put the
    # bytes. Matches `sentinel/run.py` and `api/sentinel_routes.py` — three copies of
    # one context is two too many, which is why `sentinel/context.py` owns the ids.
    blobs: object = None


# Discovered, not listed. An earlier version imported two scenario modules by name
# and slice 5b's four scenarios were therefore never run by pytest at all.
load_scenarios()


@pytest.fixture
async def ctx(live_settings):
    import seed as seed_module

    await seed_module.seed()
    app = create_app(live_settings)
    engine = create_async_engine(live_settings.app_dsn)
    app.state.engine = engine

    async with engine.connect() as conn:
        ids = await load_ids(conn)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        yield Ctx(client=client, engine=engine, ids=ids, blobs=app.state.blobs)
    await engine.dispose()


# --- the scenarios themselves -------------------------------------------------

async def test_every_registered_scenario_passes(ctx):
    results = await run_all(ctx)
    failures = [r for r in results if not r.ok]
    assert not failures, "\n".join(
        f"  [{r.severity}] {r.id} ({r.outcome}): {r.invariant}\n"
        f"      expected: {r.expected}\n"
        f"      actual:   {r.actual}"
        for r in failures
    )


async def test_slice_3_registered_the_scenarios_it_promised(ctx):
    ids = {s.id for s in REGISTRY if s.slice_id == "3"}
    assert len(ids) >= 6, f"slice 3 registered only {len(ids)} scenarios: {sorted(ids)}"


async def test_each_result_carries_enough_to_be_read_by_a_stranger(ctx):
    for result in await run_all(ctx):
        assert result.invariant and result.setup and result.expected and result.actual
        assert result.severity in set(Severity)
        assert result.at is not None


def test_every_scenario_file_is_actually_registered():
    """The guard for how slice 5b's four scenarios went unrun by pytest for a while.

    This file used to import two scenario modules by name. `sentinel/run.py` imported
    three. The CLI was therefore checking fifteen things and the test suite eleven, and
    nothing said so — the four that only ran by hand were the newest and least proven.
    Registration is discovery now, and this asserts the discovery reaches every file.
    """
    from pathlib import Path

    from sentinel.context import load_scenarios

    load_scenarios()
    slices = {s.slice_id for s in REGISTRY}
    files = {
        path.stem.removeprefix("scenarios_")
        for path in (Path(__file__).resolve().parents[1] / "sentinel").glob("scenarios_*.py")
    }
    assert files, "no scenario files found at all"
    assert len(REGISTRY) >= len(files), (
        f"{len(files)} scenario files but only {len(REGISTRY)} registered scenarios"
    )
    # Each file contributes at least one slice's worth, so a file that registered
    # nothing — an import-time error swallowed somewhere — shows up as a gap.
    assert len(slices) >= len(files), f"slices {sorted(slices)} vs files {sorted(files)}"


async def test_the_critical_scenarios_are_the_disclosure_ones(ctx):
    """Severity should track disclosure of a protected identity, not tidiness."""
    critical = {s.id for s in REGISTRY if s.severity is Severity.CRITICAL}
    assert "AUTHZ-05" in critical, "autocomplete leakage must be critical"
    assert "AUTHZ-03" in critical, "sealed-record disclosure must be critical"


# --- the harness can go red ---------------------------------------------------

async def test_a_failing_scenario_is_reported_as_a_failure(ctx):
    """The test that stops the dashboard being theatre."""

    @scenario(
        id="SELFTEST-FAIL",
        invariant="none - self test",
        setup="A scenario that asserts something false.",
        expected="Reported as FAIL.",
        severity=Severity.MEDIUM,
        slice_id="selftest",
    )
    async def deliberately_failing(_ctx) -> str:
        raise AssertionError("this is supposed to fail")

    try:
        results = {r.id: r for r in await run_all(ctx)}
        assert results["SELFTEST-FAIL"].outcome is Outcome.FAIL
        assert "supposed to fail" in results["SELFTEST-FAIL"].actual
    finally:
        REGISTRY[:] = [s for s in REGISTRY if s.id != "SELFTEST-FAIL"]


async def test_an_erroring_scenario_is_not_reported_as_a_pass(ctx):
    """An exception proved nothing. Reporting it green is how a dashboard lies."""

    @scenario(
        id="SELFTEST-ERROR",
        invariant="none - self test",
        setup="A scenario that raises something other than AssertionError.",
        expected="Reported as ERROR, distinct from both PASS and FAIL.",
        severity=Severity.MEDIUM,
        slice_id="selftest",
    )
    async def deliberately_erroring(_ctx) -> str:
        raise RuntimeError("scenario is broken")

    try:
        results = {r.id: r for r in await run_all(ctx)}
        result = results["SELFTEST-ERROR"]
        assert result.outcome is Outcome.ERROR
        assert not result.ok, "an errored scenario counted as ok"
        assert "RuntimeError" in result.actual
    finally:
        REGISTRY[:] = [s for s in REGISTRY if s.id != "SELFTEST-ERROR"]


async def test_duplicate_scenario_ids_are_refused():
    with pytest.raises(ValueError, match="duplicate scenario id"):

        @scenario(
            id="AUTHZ-01",
            invariant="x", setup="x", expected="x",
            severity=Severity.MEDIUM, slice_id="selftest",
        )
        async def clashing(_ctx) -> str:
            return "unreachable"
