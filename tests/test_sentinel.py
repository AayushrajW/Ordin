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

import sentinel.scenarios_authz  # noqa: F401 - importing registers the scenarios
from api.main import create_app
from infra.tables import app_user, case_record
from sentinel.registry import REGISTRY, Outcome, Severity, run_all, scenario

pytestmark = pytest.mark.requires_db


@dataclass
class Ctx:
    client: httpx.AsyncClient
    engine: object
    ids: dict


@pytest.fixture
async def ctx(live_settings):
    import seed as seed_module

    await seed_module.seed()
    app = create_app(live_settings)
    engine = create_async_engine(live_settings.app_dsn)
    app.state.engine = engine

    ids = {}
    async with engine.connect() as conn:
        for fragment, key in (("SI Kavya", "officer"), ("PP Meera", "lapsed"),
                              ("PP Arjun", "grantee")):
            ids[key] = str(
                (
                    await conn.execute(
                        sa.select(app_user.c.id).where(
                            app_user.c.display_name.like(f"{fragment}%")
                        )
                    )
                ).scalar_one()
            )
        ids["sealed_case"] = str(
            (
                await conn.execute(
                    sa.select(case_record.c.id).where(case_record.c.access_class == "sealed")
                )
            ).scalar_one()
        )
        ids["total_cases"] = (
            await conn.execute(sa.select(sa.func.count()).select_from(case_record))
        ).scalar_one()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        yield Ctx(client=client, engine=engine, ids=ids)
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
