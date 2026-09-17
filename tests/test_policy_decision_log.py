"""Invariant 3: every decision logs the policy ID that decided it.

`Decision` has carried `policy_id`, `policy_version` and `rule_id` since slice 3a.
This is the half that makes it mean something: the decision is persisted, so "which
rule let that through, under which version of which policy?" has an answer months
later, when the policy file has moved on.

Invariant 12 constrains what a row may contain: identifiers, the effect, and the
rule that produced it. No case reference, no party name, no free text from a request.
A decision log that records *why* in prose is a decision log that eventually records
a victim's name.

The table is append-only for the same reason `audit_event` is - a decision record you
can edit afterwards answers the question you want it to answer.
"""
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from domain.policy import load_policy
from domain.subject import CaseFacts
from infra.authz import load_subject
from infra.decisions import record_decision
from infra.tables import app_user, case_record

pytestmark = pytest.mark.requires_db

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "policies" / "case_read.v1.yaml"


@pytest.fixture
async def ctx(live_settings):
    import seed as seed_module

    await seed_module.seed()
    engine = create_async_engine(live_settings.app_dsn)  # the RUNTIME role
    async with engine.connect() as conn:
        user_id = (
            await conn.execute(
                sa.select(app_user.c.id).where(app_user.c.display_name.like("SI Kavya%"))
            )
        ).scalar_one()
        subject = await load_subject(conn, user_id)
        case_id = (await conn.execute(sa.select(case_record.c.id).limit(1))).scalar_one()
        yield conn, load_policy(POLICY), subject, str(case_id)
    await engine.dispose()


async def rows(conn):
    return (
        await conn.execute(sa.text("SELECT * FROM policy_decision ORDER BY seq"))
    ).mappings().all()


async def test_a_decision_is_persisted_with_its_policy_id(ctx):
    conn, policy, subject, case_id = ctx
    decision = policy.evaluate(
        subject,
        CaseFacts(
            case_id=case_id,
            organization_id=subject.organization_id,
            jurisdiction_id=subject.jurisdiction_id,
            is_sealed=False,
            assignment_active=True,
        ),
        datetime.now(timezone.utc),
    )
    await record_decision(
        conn, decision, subject=subject, resource_type="case", resource_id=case_id
    )
    await conn.commit()
    stored = await rows(conn)
    assert stored, "nothing was written"
    last = stored[-1]
    assert last["policy_id"] == "ordin.case_read"
    assert last["policy_version"] == 1
    assert last["rule_id"] == decision.rule_id
    assert last["effect"] == decision.effect.value


async def test_denials_are_logged_not_just_allows(ctx):
    """A log that only records successes cannot answer "was this refused, and why?"."""
    conn, policy, subject, case_id = ctx

    denial = policy.evaluate(
        subject,
        CaseFacts(
            case_id=case_id,
            organization_id="somewhere-else",
            jurisdiction_id=subject.jurisdiction_id,
            is_sealed=False,
        ),
        datetime.now(timezone.utc),
    )
    assert not denial.allowed
    await record_decision(
        conn, denial, subject=subject, resource_type="case", resource_id=case_id
    )
    await conn.commit()
    assert (await rows(conn))[-1]["effect"] == "deny"


async def test_the_row_carries_no_content_only_identifiers(ctx):
    """Invariant 12. The columns themselves are the control."""
    conn, _, _, _ = ctx
    columns = {
        c["column_name"]
        for c in (
            await conn.execute(
                sa.text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'policy_decision'"
                )
            )
        ).mappings().all()
    }
    forbidden = {"case_reference", "display_name", "party_name", "detail", "message", "note"}
    assert not (columns & forbidden), f"content-shaped columns present: {columns & forbidden}"
    assert {"policy_id", "policy_version", "rule_id", "effect", "subject_user_id"} <= columns


async def test_the_runtime_role_cannot_rewrite_a_decision(ctx):
    """Append-only, same reasoning as audit_event."""
    conn, policy, subject, case_id = ctx

    decision = policy.evaluate(
        subject,
        CaseFacts(case_id=case_id, organization_id=subject.organization_id,
                  jurisdiction_id=subject.jurisdiction_id, is_sealed=False),
        datetime.now(timezone.utc),
    )
    await record_decision(
        conn, decision, subject=subject, resource_type="case", resource_id=case_id
    )
    await conn.commit()
    with pytest.raises(Exception) as exc:
        await conn.execute(sa.text("UPDATE policy_decision SET effect = 'allow'"))
    assert "permission denied" in str(exc.value).lower()


async def test_grants_confirm_the_revoke_rather_than_inferring_it(ctx):
    conn, _, _, _ = ctx
    granted = {
        r[0].upper()
        for r in (
            await conn.execute(
                sa.text(
                    "SELECT privilege_type FROM information_schema.role_table_grants "
                    "WHERE table_name = 'policy_decision' AND grantee = current_user"
                )
            )
        ).all()
    }
    assert "INSERT" in granted and "SELECT" in granted
    assert "UPDATE" not in granted and "DELETE" not in granted
