"""Invariants 7 and 9, enforced by the database rather than by convention.

The coverage pass raised this about invariant 7:

    Enforcement is at "the schema boundary", which means Pydantic, which a direct
    INSERT never reaches - so the provenance guarantee is an application-path
    guarantee unless the migration mirrors it as NOT NULL plus a CHECK.

So these tests do not go through the application at all. They insert directly, as a
worker with a database connection could, and assert the database refuses. A constraint
that only the happy path respects is not a constraint.

Two invariants meet here:

  7 (as resolved by docs/adr/0011) - a machine field must carry a source span; a
    human field may not, and must name its author instead.
  9 - AI output is always draft. Only an explicit human commit writes `verified`,
    and nothing reaches that status without naming the human.
"""
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.requires_db


@pytest.fixture
async def ctx(live_settings):
    import seed as seed_module

    await seed_module.seed()
    engine = create_async_engine(live_settings.owner_dsn)
    async with engine.connect() as conn:
        case_id = (await conn.execute(sa.text("SELECT id FROM case_record LIMIT 1"))).scalar_one()
        user_id = (await conn.execute(sa.text("SELECT id FROM app_user LIMIT 1"))).scalar_one()
        document_id, version_id = uuid.uuid4(), uuid.uuid4()
        await conn.execute(
            sa.text("INSERT INTO document (id, case_id, title) VALUES (:i,:c,'Specimen')"),
            {"i": document_id, "c": case_id},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO document_version (id, document_id, version_no, sha256) "
                "VALUES (:i,:d,1,:h)"
            ),
            {"i": version_id, "d": document_id, "h": "a" * 64},
        )
        await conn.commit()
        yield conn, {"case_id": case_id, "user_id": user_id, "version_id": version_id}
    await engine.dispose()


async def insert_field(conn, ids, **overrides):
    row = dict(
        id=uuid.uuid4(),
        version_id=ids["version_id"],
        case_id=ids["case_id"],
        field_key="complainant_name",
        value="Anjali Bhosle",
        source="regex",
        source_span_start=10,
        source_span_end=23,
        confidence=0.98,
        provider="ordin.regex",
        model="complainant_name.v1",
        prompt_version=None,
        status="draft",
        verified_by=None,
        verified_at=None,
        entered_by=None,
        entered_at=None,
    )
    row.update(overrides)
    await conn.execute(
        sa.text(
            "INSERT INTO extracted_field "
            "(id, version_id, case_id, field_key, value, source, source_span_start, "
            " source_span_end, confidence, provider, model, prompt_version, status, "
            " verified_by, verified_at, entered_by, entered_at) "
            "VALUES (:id,:version_id,:case_id,:field_key,:value,:source,:source_span_start,"
            " :source_span_end,:confidence,:provider,:model,:prompt_version,:status,"
            " :verified_by,:verified_at,:entered_by,:entered_at)"
        ),
        row,
    )


# --- invariant 7: machines must point at something ----------------------------

async def test_a_machine_field_with_a_span_is_accepted(ctx):
    conn, ids = ctx
    await insert_field(conn, ids)
    await conn.commit()


@pytest.mark.parametrize("source", ["regex", "ner", "llm"])
async def test_a_machine_field_without_a_span_is_refused_by_the_database(ctx, source):
    """The half of invariant 7 that protects something.

    Without this, a pipeline stage can assert a value it cannot point at - which is
    how an extracted field becomes an assertion rather than evidence.
    """
    conn, ids = ctx
    with pytest.raises(Exception) as exc:
        await insert_field(conn, ids, source=source, source_span_start=None,
                           source_span_end=None)
    assert "ck_machine_field_has_span" in str(exc.value)


async def test_a_human_field_may_have_no_span(ctx):
    """ADR 0011. A person reading handwriting the OCR could not has nothing to point at."""
    conn, ids = ctx
    await insert_field(
        conn, ids, source="human", source_span_start=None, source_span_end=None,
        confidence=None, provider=None, model=None,
        entered_by=ids["user_id"], entered_at=sa.text("now()").text and None,
    )
    await conn.commit()


async def test_a_human_field_must_name_its_author(ctx):
    """Accountability replaces traceability when traceability is impossible."""
    conn, ids = ctx
    with pytest.raises(Exception) as exc:
        await insert_field(conn, ids, source="human", source_span_start=None,
                           source_span_end=None, entered_by=None)
    assert "ck_human_field_has_author" in str(exc.value)


async def test_a_machine_field_may_not_claim_a_human_author(ctx):
    """The same constraint in the other direction: regex output is not somebody's word."""
    conn, ids = ctx
    with pytest.raises(Exception) as exc:
        await insert_field(conn, ids, source="regex", entered_by=ids["user_id"])
    assert "ck_human_field_has_author" in str(exc.value)


async def test_a_reversed_span_is_refused(ctx):
    conn, ids = ctx
    with pytest.raises(Exception) as exc:
        await insert_field(conn, ids, source_span_start=50, source_span_end=10)
    assert "ck_field_span_ordered" in str(exc.value)


async def test_an_unknown_source_is_refused(ctx):
    """The enum is closed. A new extraction method is a migration, not a free string."""
    conn, ids = ctx
    with pytest.raises(Exception) as exc:
        await insert_field(conn, ids, source="vibes")
    assert "ck_field_source" in str(exc.value)


# --- invariant 9: only a human commits ----------------------------------------

async def test_a_pipeline_cannot_write_verified(ctx):
    """Invariant 9, enforced where a pipeline stage actually runs.

    "No pipeline stage may write verified" is a rule a stage can simply break. The
    constraint makes it impossible to reach that status without naming a human.
    """
    conn, ids = ctx
    with pytest.raises(Exception) as exc:
        await insert_field(conn, ids, status="verified", verified_by=None)
    assert "ck_verified_names_a_human" in str(exc.value)


async def test_a_human_commit_is_permitted_and_names_the_committer(ctx):
    conn, ids = ctx
    await insert_field(conn, ids, status="verified", verified_by=ids["user_id"])
    await conn.commit()
    row = (
        await conn.execute(
            sa.text(
                "SELECT status, verified_by FROM extracted_field "
                "WHERE version_id = :v ORDER BY created_at DESC LIMIT 1"
            ),
            {"v": ids["version_id"]},
        )
    ).mappings().one()
    assert row["status"] == "verified" and row["verified_by"] is not None


async def test_an_unknown_status_is_refused(ctx):
    conn, ids = ctx
    with pytest.raises(Exception) as exc:
        await insert_field(conn, ids, status="probably_fine")
    assert "ck_field_status" in str(exc.value)


# --- one field per source per version -----------------------------------------

async def test_the_same_field_cannot_be_extracted_twice_by_the_same_source(ctx):
    """Part of what makes re-running the pipeline idempotent rather than duplicating."""
    conn, ids = ctx
    await insert_field(conn, ids)
    await conn.commit()
    with pytest.raises(Exception) as exc:
        await insert_field(conn, ids)
    assert "uq_field_per_source" in str(exc.value)


async def test_a_human_may_correct_a_machine_field_without_colliding(ctx):
    """regex and human are different sources, so both rows coexist.

    The verification UI shows the machine draft and the human's correction as
    distinct provenance rather than overwriting one with the other.
    """
    conn, ids = ctx
    await insert_field(conn, ids, source="regex")
    await insert_field(
        conn, ids, source="human", value="Anjali Bhosale", source_span_start=None,
        source_span_end=None, confidence=None, provider=None, model=None,
        entered_by=ids["user_id"],
    )
    await conn.commit()
    count = (
        await conn.execute(
            sa.text(
                "SELECT count(*) FROM extracted_field "
                "WHERE version_id = :v AND field_key = 'complainant_name'"
            ),
            {"v": ids["version_id"]},
        )
    ).scalar_one()
    assert count == 2
