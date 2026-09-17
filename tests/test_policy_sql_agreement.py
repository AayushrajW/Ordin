"""The Python evaluator and the SQL filter must never disagree.

This is the test the whole arrangement in `domain/predicates.py` and
`infra/authz_sql.py` exists to make possible, and it is the one the obvious design
cannot have.

The obvious design is a YAML policy describing the rules and a hand-written SQL
fragment implementing them. Two encodings of one intent, drifting silently - and
because CLAUDE.md requires the policy tests to run with no application and no
database, those tests stay green while the SQL does something else entirely. The
policy file becomes decorative and nobody finds out until a judge types three letters
into a search box.

Here both halves key off one registry of predicate names, the policy loader rejects a
name with no Python implementation, the filter compiler rejects one with no SQL
implementation, and this test asserts the two produce identical answers for every
subject against every case in the seeded data.
"""
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from domain.policy import load_policy
from infra.authz import authorized_case_ids, load_case_facts, load_subject
from infra.authz_sql import SQL_REGISTRY
from infra.tables import AUTHZ_TABLES, app_user, case_record

pytestmark = pytest.mark.requires_db

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "policies" / "case_read.v1.yaml"


@pytest.fixture
async def conn(live_settings):
    import seed as seed_module

    await seed_module.seed()
    engine = create_async_engine(live_settings.owner_dsn)
    async with engine.connect() as connection:
        yield connection
    await engine.dispose()


# --- the registries must not drift -------------------------------------------

def test_both_registries_define_exactly_the_same_predicates():
    """A predicate added to one side only is a test failure, not a silent divergence."""
    from domain.predicates import REGISTRY

    assert set(REGISTRY) == set(SQL_REGISTRY), (
        f"only in Python: {set(REGISTRY) - set(SQL_REGISTRY)}; "
        f"only in SQL: {set(SQL_REGISTRY) - set(REGISTRY)}"
    )


def test_the_policy_only_names_predicates_both_sides_implement():
    policy = load_policy(POLICY)
    named = {c.predicate for rule in policy.rules for c in rule.conditions}
    assert named <= set(SQL_REGISTRY), f"no SQL implementation for {named - set(SQL_REGISTRY)}"


# --- the agreement itself ----------------------------------------------------

async def test_evaluator_and_sql_filter_agree_on_every_subject_and_case(conn):
    policy = load_policy(POLICY)
    at = datetime.now(timezone.utc)

    user_ids = (await conn.execute(sa.select(app_user.c.id))).scalars().all()
    case_ids = (await conn.execute(sa.select(case_record.c.id))).scalars().all()
    assert user_ids and case_ids, "seed produced nothing to compare"

    disagreements = []
    compared = 0

    for user_id in user_ids:
        subject = await load_subject(conn, user_id)
        assert subject is not None

        # What SQL says this subject may see, in one query.
        visible = {
            str(cid)
            for cid in (
                await conn.execute(authorized_case_ids(policy, subject, at))
            ).scalars().all()
        }

        for case_id in case_ids:
            facts = await load_case_facts(conn, subject, str(case_id), at)
            decision = policy.evaluate(subject, facts, at)
            sql_allows = str(case_id) in visible
            compared += 1
            if decision.allowed != sql_allows:
                disagreements.append(
                    f"user={subject.user_id} case={case_id}: "
                    f"evaluator={'allow' if decision.allowed else 'deny'} "
                    f"(rule {decision.rule_id}) but SQL="
                    f"{'allow' if sql_allows else 'deny'}"
                )

    assert not disagreements, (
        f"{len(disagreements)} of {compared} decisions disagree:\n  "
        + "\n  ".join(disagreements)
    )
    assert compared >= 12, f"only {compared} comparisons - the seed is too thin to prove much"


async def test_the_comparison_covers_both_outcomes(conn):
    """A test where everything denies would pass while proving nothing."""
    policy = load_policy(POLICY)
    at = datetime.now(timezone.utc)

    outcomes = set()
    for user_id in (await conn.execute(sa.select(app_user.c.id))).scalars().all():
        subject = await load_subject(conn, user_id)
        for case_id in (await conn.execute(sa.select(case_record.c.id))).scalars().all():
            facts = await load_case_facts(conn, subject, str(case_id), at)
            outcomes.add(policy.evaluate(subject, facts, at).allowed)

    assert outcomes == {True, False}, (
        f"every decision came out {outcomes} - the agreement test is vacuous"
    )


async def test_each_denial_rule_actually_fires_somewhere(conn):
    """Otherwise a rule could be wrong and never be exercised."""
    policy = load_policy(POLICY)
    at = datetime.now(timezone.utc)

    fired = set()
    for user_id in (await conn.execute(sa.select(app_user.c.id))).scalars().all():
        subject = await load_subject(conn, user_id)
        for case_id in (await conn.execute(sa.select(case_record.c.id))).scalars().all():
            facts = await load_case_facts(conn, subject, str(case_id), at)
            fired.add(policy.evaluate(subject, facts, at).rule_id)

    # The seed is built to exercise these specifically.
    for rule_id in ("lapsed-clearance", "sealed-without-clearance", "designated-officer",
                    "purpose-limited-grant", "default-deny"):
        assert rule_id in fired, (
            f"rule {rule_id!r} never fired against the seed; it is untested in practice. "
            f"fired: {sorted(fired)}"
        )
