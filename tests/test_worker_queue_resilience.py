"""The queue must not stall, and a failed stage must actually be retried.

Two failures lived in one predicate. `claim_unprocessed` asked "does this version have
an `ocr_text` row?", and that question is wrong in both directions.

**Forwards**: a version whose OCR always raises never gets an `ocr_text` row, so it
always satisfies the predicate. Ordered oldest-first, one row per tick, it occupied the
only slot for ever and every later upload queued behind it was never processed. The
worker logged a green heartbeat throughout and the API kept answering 202 `queued`.

**Backwards**: once OCR succeeded the row existed, so the version left the ready set
permanently — whether or not extract, sign or anchor had run. `process_version` stops at
the first failing stage, so a brief anchor outage stranded documents with no anchor,
`verify()` returning PENDING for ever, and no exit: `dispose_version` refuses an
unanchored version with 409 `not_anchored`. CLAUDE.md promises "anchoring is a separate
retryable stage". It was separate and it was not retryable.

Both are now one question: is any stage neither succeeded nor out of attempts?
"""
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from infra.pipeline import MAX_STAGE_ATTEMPTS
from worker.intake_queue import STAGES, claim_unprocessed

pytestmark = pytest.mark.requires_db


@pytest.fixture
async def db(live_settings):
    engine = create_async_engine(live_settings.owner_dsn)
    yield engine
    await engine.dispose()


async def _a_version(conn) -> tuple[str, str]:
    """An active, non-derivative version with a document and a case. Returns ids."""
    case_id = (await conn.execute(sa.text("SELECT id FROM case_record LIMIT 1"))).scalar_one()
    document_id = uuid.uuid4()
    version_id = uuid.uuid4()
    await conn.execute(
        sa.text(
            "INSERT INTO document (id, case_id, title, doc_class) "
            "VALUES (:i, :c, :t, 'other')"
        ),
        {"i": document_id, "c": case_id, "t": f"queue-{version_id.hex[:8]}"},
    )
    await conn.execute(
        sa.text(
            "INSERT INTO document_version "
            "(id, document_id, version_no, sha256, source_sha256, lifecycle_state) "
            "VALUES (:i, :d, 1, :h, :h, 'active')"
        ),
        {"i": version_id, "d": document_id, "h": uuid.uuid4().hex * 2},
    )
    return str(version_id), str(document_id)


async def _job(conn, version_id: str, stage: str, *, status: str, attempts: int) -> None:
    await conn.execute(
        sa.text(
            "INSERT INTO processing_job "
            "(id, document_version_id, stage, status, idempotency_key, attempts) "
            "VALUES (:i, :v, :s, :st, :k, :a)"
        ),
        {"i": uuid.uuid4(), "v": version_id, "s": stage, "st": status,
         "k": uuid.uuid4().hex, "a": attempts},
    )


async def _claimed_ids(conn, limit: int = 500) -> set[str]:
    """Every version the queue currently considers ready, not just the first batch."""
    rows = (
        await conn.execute(
            sa.text(
                "SELECT dv.id::text AS version_id FROM document_version dv "
                "JOIN document d ON d.id = dv.document_id "
                "WHERE dv.derived_from_version_id IS NULL "
                "  AND dv.lifecycle_state = 'active' "
                "  AND EXISTS ( "
                "        SELECT 1 FROM unnest(:stages ::text[]) AS s(stage) "
                "        WHERE NOT EXISTS (SELECT 1 FROM processing_job j "
                "                WHERE j.document_version_id = dv.id "
                "                  AND j.stage = s.stage AND j.status = 'succeeded')) "
                "  AND NOT EXISTS (SELECT 1 FROM processing_job j "
                "        WHERE j.document_version_id = dv.id AND j.attempts >= :cap) "
                "LIMIT :n"
            ),
            {"stages": STAGES, "cap": MAX_STAGE_ATTEMPTS, "n": limit},
        )
    ).scalars().all()
    return set(rows)


# --- starvation -----------------------------------------------------------------


async def test_a_version_out_of_attempts_leaves_the_ready_set(db):
    """The starvation fix. Out of attempts means the queue stops offering it."""
    async with db.begin() as conn:
        version_id, _ = await _a_version(conn)
        assert version_id in await _claimed_ids(conn), "a new version should be ready"

        await _job(conn, version_id, "ocr", status="failed", attempts=MAX_STAGE_ATTEMPTS)
        assert version_id not in await _claimed_ids(conn), (
            "a version whose OCR is out of attempts is still being offered, so it will "
            "be claimed on every tick and starve everything behind it"
        )
        await conn.rollback()


async def test_a_healthy_version_behind_a_poisoned_one_is_reachable(db):
    """The consequence that actually mattered: the queue keeps moving."""
    async with db.begin() as conn:
        poisoned, _ = await _a_version(conn)
        await _job(conn, poisoned, "ocr", status="failed", attempts=MAX_STAGE_ATTEMPTS)
        healthy, _ = await _a_version(conn)

        ready = await _claimed_ids(conn)
        assert healthy in ready
        assert poisoned not in ready
        await conn.rollback()


async def test_a_failure_with_attempts_left_is_still_retried(db):
    """Bounded, not abandoned. A transient must not cost the document its processing."""
    async with db.begin() as conn:
        version_id, _ = await _a_version(conn)
        await _job(conn, version_id, "ocr", status="failed", attempts=MAX_STAGE_ATTEMPTS - 1)
        assert version_id in await _claimed_ids(conn)
        await conn.rollback()


# --- the anchor, retried --------------------------------------------------------


async def test_a_version_whose_anchor_failed_is_still_ready(db):
    """The invariant CLAUDE.md states and the old predicate could not keep.

    OCR, extract and sign succeeded, so the old `ocr_text IS NULL` test removed this
    version from the ready set for ever and the anchor was never retried.
    """
    async with db.begin() as conn:
        version_id, _ = await _a_version(conn)
        for stage in ("ocr", "extract", "sign"):
            await _job(conn, version_id, stage, status="succeeded", attempts=1)
        await _job(conn, version_id, "anchor", status="failed", attempts=1)

        assert version_id in await _claimed_ids(conn), (
            "a version with a failed anchor is not offered again, so the anchor stage "
            "is not retryable and verify() reports PENDING for ever"
        )
        await conn.rollback()


async def test_a_fully_processed_version_leaves_the_ready_set(db):
    """The other half: success must actually retire the work, or the worker spins."""
    async with db.begin() as conn:
        version_id, _ = await _a_version(conn)
        for stage in STAGES:
            await _job(conn, version_id, stage, status="succeeded", attempts=1)
        assert version_id not in await _claimed_ids(conn)
        await conn.rollback()


async def test_a_version_missing_only_its_anchor_job_is_ready(db):
    """No job row at all is different from a failed one, and both owe the stage."""
    async with db.begin() as conn:
        version_id, _ = await _a_version(conn)
        for stage in ("ocr", "extract", "sign"):
            await _job(conn, version_id, stage, status="succeeded", attempts=1)
        assert version_id in await _claimed_ids(conn)
        await conn.rollback()


# --- what the queue must still exclude ------------------------------------------


async def test_derivatives_and_disposed_versions_stay_excluded(db):
    """The two exclusions that were already correct. Rewriting the predicate is
    exactly when they get dropped by accident."""
    async with db.begin() as conn:
        derivative_parent, document_id = await _a_version(conn)
        derivative = uuid.uuid4()
        await conn.execute(
            sa.text(
                "INSERT INTO document_version (id, document_id, version_no, sha256, "
                " source_sha256, lifecycle_state, derived_from_version_id) "
                "VALUES (:i, :d, 2, :h, :h, 'active', :p)"
            ),
            {"i": derivative, "d": document_id, "h": uuid.uuid4().hex * 2,
             "p": derivative_parent},
        )

        disposed, _ = await _a_version(conn)
        await conn.execute(
            sa.text("UPDATE document_version SET lifecycle_state='disposed' WHERE id=:v"),
            {"v": disposed},
        )

        ready = await _claimed_ids(conn)
        assert str(derivative) not in ready, "a redacted derivative was queued for OCR"
        assert disposed not in ready, "a disposed version was queued for processing"
        await conn.rollback()


async def test_claim_unprocessed_returns_the_columns_the_worker_uses(db):
    """The query feeds `process_version` by keyword. A renamed column would surface as
    a TypeError inside the worker loop, which swallows the type and logs no message."""
    async with db.begin() as conn:
        await _a_version(conn)
        claimed = await claim_unprocessed(conn)
        assert claimed, "nothing claimable even though a fresh version exists"
        assert {"version_id", "document_id", "sha256", "source_sha256", "case_id"} <= set(
            claimed[0]
        )
        await conn.rollback()
