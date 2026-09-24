"""Invariant 1: the predicate is inside the query, on every surface.

CLAUDE.md is specific about what that means and about how it is tested:

    Authorization predicates are applied inside the data query, never after -
    before scoring, ranking, pagination, aggregation, COUNT, export, autocomplete
    and embedding retrieval. Post-filtering leaks through result counts, page
    behaviour and suggestion lists. Autocomplete is the worst offender: three
    letters must never surface a name from an unauthorised case.

and docs/PLAN.md:

    tests asserting a smaller COUNT - not a filtered page

The distinction matters. A filtered page proves the rows were removed before the
caller saw them. A smaller count proves they were removed before the database
counted them, which is the only version that does not leak through a total, a
last-page number or an export row count (threat INS-03).

These tests run at the query layer rather than over HTTP, because that is where the
invariant lives. The HTTP surfaces arrive in slice 3b and inherit it by construction:
every one of them starts from `authorized_cases()`.
"""
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from domain.policy import latest_policy_path, load_policy
from infra.authz import authorized_case_ids, authorized_cases, load_subject
from infra.tables import app_user, case_record, party

pytestmark = pytest.mark.requires_db

ROOT = Path(__file__).resolve().parents[1]
# Resolved, never spelled out. Five test files used to hardcode `case_read.v1.yaml`,
# so the version bump in ADR 0029 would have left the whole suite green while
# asserting against a policy the running system no longer loads.
POLICY = latest_policy_path(ROOT / "policies", "case_read")
AT = datetime.now(timezone.utc)


@pytest.fixture
async def ctx(live_settings):
    """Seeded database, the policy, and the subjects the assertions name."""
    import seed as seed_module

    await seed_module.seed()
    engine = create_async_engine(live_settings.owner_dsn)
    async with engine.connect() as conn:
        policy = load_policy(POLICY)
        subjects = {}
        for name_fragment, key in (
            ("SI Kavya", "officer"),        # designated on one case only
            ("SHO Rahul", "senior"),        # senior, designated on one case
            ("PP Arjun", "grantee"),        # other organization, live grant
            ("PP Meera", "lapsed"),         # live grant, LAPSED clearance
        ):
            user_id = (
                await conn.execute(
                    sa.select(app_user.c.id).where(
                        app_user.c.display_name.like(f"{name_fragment}%")
                    )
                )
            ).scalar_one()
            subjects[key] = await load_subject(conn, user_id)
        total = (
            await conn.execute(sa.select(sa.func.count()).select_from(case_record))
        ).scalar_one()
        yield conn, policy, subjects, total
    await engine.dispose()


async def visible_count(conn, policy, subject) -> int:
    """COUNT with the predicate inside it, which is the whole point."""
    inner = authorized_case_ids(policy, subject, AT).subquery()
    return (
        await conn.execute(sa.select(sa.func.count()).select_from(inner))
    ).scalar_one()


# --- COUNT -------------------------------------------------------------------

async def test_count_is_smaller_for_a_subject_who_cannot_see_everything(ctx):
    conn, policy, subjects, total = ctx
    seen = await visible_count(conn, policy, subjects["officer"])
    assert 0 < seen < total, (
        f"the officer counted {seen} of {total} cases; a count equal to the total "
        f"means the predicate is not inside the aggregate"
    )


async def test_seniority_does_not_widen_the_count(ctx):
    """CLAUDE.md: designation is decisive; seniority implies nothing."""
    conn, policy, subjects, total = ctx
    senior = await visible_count(conn, policy, subjects["senior"])
    assert senior < total, (
        f"the senior officer counted {senior} of {total} - rank is leaking into the "
        f"decision, which the authorization model explicitly forbids"
    )


async def test_a_lapsed_clearance_counts_nothing_despite_a_live_grant(ctx):
    """The three validity clocks intersect, they do not union (threat AZM-06)."""
    conn, policy, subjects, _ = ctx
    assert await visible_count(conn, policy, subjects["lapsed"]) == 0


# --- list and pagination -----------------------------------------------------

async def test_list_returns_only_authorized_rows(ctx):
    conn, policy, subjects, total = ctx
    rows = (await conn.execute(authorized_cases(policy, subjects["officer"], AT))).all()
    assert 0 < len(rows) < total


async def test_pagination_cannot_reach_an_unauthorized_row(ctx):
    """Page 2 of a filtered set must not contain what page 1 hid.

    If the predicate were applied after paging, a large enough offset would walk
    straight into rows the caller cannot see.
    """
    conn, policy, subjects, _ = ctx
    allowed = {
        str(c)
        for c in (
            await conn.execute(authorized_case_ids(policy, subjects["officer"], AT))
        ).scalars().all()
    }
    for offset in range(0, 5):
        page = (
            await conn.execute(
                authorized_cases(policy, subjects["officer"], AT).limit(1).offset(offset)
            )
        ).all()
        for row in page:
            assert str(row.id) in allowed, f"offset {offset} surfaced an unauthorized case"


# --- export ------------------------------------------------------------------

async def test_export_row_count_is_smaller(ctx):
    """An export is just an unpaged read, and leaks the same way through its size."""
    conn, policy, subjects, total = ctx
    exported = (
        await conn.execute(authorized_cases(policy, subjects["officer"], AT))
    ).all()
    assert len(exported) < total


# --- autocomplete, the worst offender ---------------------------------------

async def autocomplete(conn, policy, subject, prefix: str):
    """Party-name suggestions, scoped by the same case predicate.

    The join to the authorized case set is what makes this safe. Querying `party`
    directly and filtering the results afterwards is the bug.
    """
    allowed = authorized_case_ids(policy, subject, AT).subquery()
    return (
        await conn.execute(
            sa.select(party.c.display_name)
            .join(allowed, allowed.c.id == party.c.case_id)
            .where(party.c.display_name.ilike(f"%{prefix}%"))
        )
    ).scalars().all()


async def test_three_letters_do_not_surface_a_name_from_an_unauthorized_case(ctx):
    """The sentence in CLAUDE.md that this file exists for.

    'Sunita Kale' is a victim on the sealed case. The officer has no clearance for
    it, so no prefix of that name may ever appear in their suggestions.
    """
    conn, policy, subjects, _ = ctx
    for prefix in ("Sun", "Kal", "unit"):
        names = await autocomplete(conn, policy, subjects["officer"], prefix)
        assert not any("Sunita" in n for n in names), (
            f"autocomplete on {prefix!r} surfaced a name from the sealed case: {names}"
        )


async def test_autocomplete_still_works_for_authorized_names(ctx):
    """A suggestion box that returns nothing would pass the test above trivially."""
    conn, policy, subjects, _ = ctx
    names = await autocomplete(conn, policy, subjects["officer"], "Anj")
    assert any("Anjali" in n for n in names), (
        f"authorized suggestions are missing too - the test above proves nothing: {names}"
    )


async def test_autocomplete_count_differs_between_subjects(ctx):
    conn, policy, subjects, _ = ctx
    officer = await autocomplete(conn, policy, subjects["officer"], "a")
    lapsed = await autocomplete(conn, policy, subjects["lapsed"], "a")
    assert len(lapsed) == 0 < len(officer)


# --- single-object fetch -----------------------------------------------------

async def test_fetch_by_id_is_filtered_too(ctx):
    """The surface BOOTSTRAP's acceptance list omits, and the easiest one to get wrong.

    A hand-written detail endpoint doing `session.get(Case, id)` bypasses the filter
    entirely (threat INS-01), so the id lookup must go through the same predicate.
    """
    conn, policy, subjects, _ = ctx
    sealed_id = (
        await conn.execute(
            sa.select(case_record.c.id).where(case_record.c.access_class == "sealed")
        )
    ).scalar_one()

    found = (
        await conn.execute(
            authorized_cases(policy, subjects["officer"], AT).where(
                case_record.c.id == sealed_id
            )
        )
    ).one_or_none()
    assert found is None, "fetch by id returned a sealed case to an unclearanced officer"


async def test_a_denied_fetch_is_indistinguishable_from_a_missing_one(ctx):
    """Otherwise the response is an existence oracle (threat INS-04)."""
    conn, policy, subjects, _ = ctx
    import uuid

    sealed_id = (
        await conn.execute(
            sa.select(case_record.c.id).where(case_record.c.access_class == "sealed")
        )
    ).scalar_one()
    nonexistent = uuid.uuid4()

    denied = (
        await conn.execute(
            authorized_cases(policy, subjects["officer"], AT).where(
                case_record.c.id == sealed_id
            )
        )
    ).one_or_none()
    missing = (
        await conn.execute(
            authorized_cases(policy, subjects["officer"], AT).where(
                case_record.c.id == nonexistent
            )
        )
    ).one_or_none()
    assert denied is missing is None


# --- search ------------------------------------------------------------------

async def test_search_is_scoped_by_the_same_predicate(ctx):
    """Postgres full-text search is the retrieval path; it gets the same treatment."""
    conn, policy, subjects, total = ctx
    allowed = authorized_case_ids(policy, subjects["officer"], AT).subquery()
    hits = (
        await conn.execute(
            sa.select(case_record.c.reference)
            .join(allowed, allowed.c.id == case_record.c.id)
            .where(case_record.c.reference.ilike("VRN-%"))
        )
    ).scalars().all()
    assert 0 < len(hits) < total


async def test_search_by_a_grantee_is_scoped_to_the_granted_case(ctx):
    """Cross-organization access exists only through the grant, and only for it."""
    conn, policy, subjects, _ = ctx
    allowed = authorized_case_ids(policy, subjects["grantee"], AT).subquery()
    hits = (
        await conn.execute(
            sa.select(case_record.c.reference)
            .join(allowed, allowed.c.id == case_record.c.id)
            .where(case_record.c.reference.ilike("VRN-%"))
        )
    ).scalars().all()
    assert len(hits) == 1, f"the grantee saw {len(hits)} cases; the grant covers one"
