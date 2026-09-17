"""The seed loads, and loads the shape slice 3 needs.

Slice 2's acceptance is "seed loads 3 cases across 2 organizations". That is the
minimum; these assertions also pin the *structure* the authorization tests in slice 3
will depend on, so a well-meaning edit to seed.py that flattens it fails here rather
than silently making slice 3's denial tests vacuous.

A denial test only proves something if the thing being denied actually exists.
"""
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.requires_db


@pytest.fixture
async def seeded(live_settings):
    import seed as seed_module

    await seed_module.seed()
    engine = create_async_engine(live_settings.owner_dsn)
    yield engine
    await engine.dispose()


async def scalar(engine, sql: str):
    async with engine.connect() as conn:
        return (await conn.execute(sa.text(sql))).scalar_one()


# --- the stated acceptance ---------------------------------------------------

async def test_three_cases_across_two_organizations(seeded):
    assert await scalar(seeded, "SELECT count(*) FROM case_record") == 3
    assert await scalar(seeded, "SELECT count(*) FROM organization") == 2


async def test_the_two_organizations_are_different_kinds(seeded):
    """Police and prosecution, so cross-organization access has a real shape."""
    kinds = await scalar(seeded, "SELECT count(DISTINCT kind) FROM organization")
    assert kinds == 2


# --- the structure slice 3 will actually test against ------------------------

async def test_an_officer_is_designated_on_one_case_and_not_another(seeded):
    """Without this, "designation is decisive" has nothing to demonstrate."""
    designated = await scalar(
        seeded,
        "SELECT count(*) FROM case_assignment a "
        "JOIN app_user u ON u.id = a.user_id "
        "WHERE u.display_name LIKE 'SI %' AND a.valid_to IS NULL",
    )
    total_cases = await scalar(seeded, "SELECT count(*) FROM case_record")
    assert 0 < designated < total_cases, (
        f"the SI is designated on {designated} of {total_cases} cases; the negative "
        f"case for a designation test does not exist"
    )


async def test_a_lapsed_assignment_exists(seeded):
    """One of the three independent validity clocks (threat AZM-06)."""
    assert await scalar(
        seeded, "SELECT count(*) FROM case_assignment WHERE valid_to < now()"
    ) >= 1


async def test_both_a_live_and_an_expired_grant_exist(seeded):
    """The other two clocks. An expiry test needs an expired row to find."""
    assert await scalar(
        seeded, "SELECT count(*) FROM access_grant WHERE expires_at > now()"
    ) >= 1
    assert await scalar(
        seeded, "SELECT count(*) FROM access_grant WHERE expires_at < now()"
    ) >= 1


async def test_a_lapsed_clearance_exists(seeded):
    assert await scalar(
        seeded,
        "SELECT count(*) FROM app_user WHERE clearance_valid_to IS NOT NULL "
        "AND clearance_valid_to < now()",
    ) >= 1


async def test_a_sealed_case_exists(seeded):
    assert await scalar(
        seeded, "SELECT count(*) FROM case_record WHERE access_class = 'sealed'"
    ) == 1


async def test_every_grant_is_case_scoped(seeded):
    """docs/adr/0005: organization-wide grants have no representation at all."""
    assert await scalar(
        seeded, "SELECT count(*) FROM access_grant WHERE case_id IS NULL"
    ) == 0


async def test_a_cross_organization_grantee_exists(seeded):
    """Someone whose only route into a case is an explicit grant, never a role."""
    assert await scalar(
        seeded,
        "SELECT count(*) FROM access_grant g "
        "JOIN app_user u ON u.id = g.grantee_id "
        "JOIN post p ON p.id = u.post_id "
        "JOIN case_record c ON c.id = g.case_id "
        "WHERE p.organization_id <> c.organization_id",
    ) >= 1


# --- honesty -----------------------------------------------------------------

async def test_seed_is_idempotent(seeded):
    """Running it twice must not double the rows - `tasks.py seed` will be re-run."""
    import seed as seed_module

    await seed_module.seed()
    assert await scalar(seeded, "SELECT count(*) FROM case_record") == 3
