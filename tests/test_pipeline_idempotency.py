"""Slice 5a's acceptance criterion, and the reliability invariant behind it.

    Running the pipeline twice on one upload yields exactly one version, one
    extraction run, one field set, one anchor.

CLAUDE.md is blunt that this "is a test, not an intention", which is why the
assertions count rows rather than inspecting control flow. A pipeline that skips
correctly and a pipeline that happens not to have run twice look identical from the
inside; only the row counts distinguish them.

The document is a real fixture and the whole thread runs end to end against the real
database. The text stage here is `EmbeddedTextLayer` rather than Tesseract, on purpose:
this file counts rows, and a real OCR pass per run would add minutes without changing
anything it proves. `test_pipeline_ocr.py` runs the same thread with real Tesseract, so
the OCR path is covered where it matters rather than everywhere it is slow.
"""
import uuid
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine

from domain.enums import JobStatus
from infra.anchor import LocalAnchorStore
from infra.blobstore import LocalBlobStore
from infra.esign import SimulatedESignProvider
from infra.pipeline import Pipeline, idempotency_key
from infra.textsource import EmbeddedTextLayer, TextSourceUnavailable

pytestmark = pytest.mark.requires_db

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "corpus" / "complaint-0001.pdf"
NOW = datetime.now(timezone.utc)


@pytest.fixture
async def ctx(live_settings, tmp_path):
    import seed as seed_module

    await seed_module.seed()
    engine = create_async_engine(live_settings.owner_dsn)
    pipeline = Pipeline(
        blobs=LocalBlobStore(tmp_path / "blobs"),
        # Text layer rather than Tesseract for the idempotency tests: this file is
        # about counting rows, and a real OCR pass per run would add minutes without
        # changing what is being proved. test_pipeline_ocr.py uses real OCR.
        text_source=EmbeddedTextLayer(),
        signer=SimulatedESignProvider("test-secret"),
        anchors=LocalAnchorStore(),
    )
    async with engine.connect() as conn:
        case_id = (await conn.execute(sa.text("SELECT id FROM case_record LIMIT 1"))).scalar_one()
        actor_id = (await conn.execute(sa.text("SELECT id FROM app_user LIMIT 1"))).scalar_one()
        yield conn, pipeline, case_id, actor_id
    await engine.dispose()


async def counts(conn, version_id) -> dict:
    async def one(sql, **params):
        return (await conn.execute(sa.text(sql), params)).scalar_one()

    return {
        "versions": await one(
            "SELECT count(*) FROM document_version WHERE id = :v", v=version_id
        ),
        "ocr_text": await one("SELECT count(*) FROM ocr_text WHERE version_id = :v", v=version_id),
        "fields": await one(
            "SELECT count(*) FROM extracted_field WHERE version_id = :v", v=version_id
        ),
        "anchors": await one(
            "SELECT count(*) FROM anchor_record WHERE version_id = :v", v=version_id
        ),
        "jobs": await one(
            "SELECT count(*) FROM processing_job WHERE document_version_id = :v", v=version_id
        ),
    }


# --- the acceptance criterion --------------------------------------------------

async def test_running_twice_yields_exactly_one_of_everything(ctx):
    conn, pipeline, case_id, actor_id = ctx
    data = FIXTURE.read_bytes()

    first = await pipeline.run(
        conn, case_id=case_id, actor_id=actor_id, filename="complaint.pdf", data=data, at=NOW
    )
    await conn.commit()
    assert first.ok, [s for s in first.stages if s.status == JobStatus.FAILED]
    after_first = await counts(conn, first.version_id)

    second = await pipeline.run(
        conn, case_id=case_id, actor_id=actor_id, filename="complaint.pdf", data=data, at=NOW
    )
    await conn.commit()

    assert second.version_id == first.version_id, "a second run created a second version"
    after_second = await counts(conn, first.version_id)

    assert after_second == after_first, (
        f"the second run changed the row counts:\n"
        f"  after first:  {after_first}\n"
        f"  after second: {after_second}"
    )
    assert after_second["versions"] == 1
    assert after_second["ocr_text"] == 1
    assert after_second["anchors"] == 1
    assert after_second["fields"] >= 1


async def test_the_second_run_reports_every_stage_as_skipped(ctx):
    """Skipping is the mechanism; the row counts above are the proof."""
    conn, pipeline, case_id, actor_id = ctx
    data = FIXTURE.read_bytes()
    await pipeline.run(conn, case_id=case_id, actor_id=actor_id, filename="c.pdf",
                       data=data, at=NOW)
    await conn.commit()
    second = await pipeline.run(conn, case_id=case_id, actor_id=actor_id, filename="c.pdf",
                                data=data, at=NOW)
    await conn.commit()
    assert all(s.skipped for s in second.stages), [
        (s.stage, s.skipped) for s in second.stages
    ]


async def test_running_three_times_is_still_one_of_everything(ctx):
    conn, pipeline, case_id, actor_id = ctx
    data = FIXTURE.read_bytes()
    for _ in range(3):
        result = await pipeline.run(conn, case_id=case_id, actor_id=actor_id,
                                    filename="c.pdf", data=data, at=NOW)
        await conn.commit()
    final = await counts(conn, result.version_id)
    assert final["ocr_text"] == 1 and final["anchors"] == 1


# --- the key itself, per ADR 0004 ----------------------------------------------

def test_the_key_is_scoped_to_the_case():
    """Threat INS-06: content alone would answer questions across a case boundary."""
    a = idempotency_key(case_id="case-a", content_sha256="d" * 64, operation="ocr")
    b = idempotency_key(case_id="case-b", content_sha256="d" * 64, operation="ocr")
    assert a != b, (
        "the same bytes in two cases share a key - uploading a document you hold "
        "into your own case would reveal it exists in a case you cannot read"
    )


def test_the_key_separates_stages():
    assert idempotency_key(case_id="c", content_sha256="d" * 64, operation="ocr") != (
        idempotency_key(case_id="c", content_sha256="d" * 64, operation="extract")
    )


def test_params_change_the_key():
    """So a corrected redaction manifest cannot return the flawed derivative."""
    plain = idempotency_key(case_id="c", content_sha256="d" * 64, operation="redact")
    with_params = idempotency_key(
        case_id="c", content_sha256="d" * 64, operation="redact",
        params={"manifest": "corrected"},
    )
    assert plain != with_params


def test_the_key_is_stable_for_identical_inputs():
    args = dict(case_id="c", content_sha256="d" * 64, operation="ocr", params={"a": 1, "b": 2})
    assert idempotency_key(**args) == idempotency_key(
        case_id="c", content_sha256="d" * 64, operation="ocr", params={"b": 2, "a": 1}
    )


# --- the same document in two cases ---------------------------------------------

async def test_the_same_bytes_in_two_cases_produce_two_versions(ctx):
    """The behaviour the case-scoped key exists to protect (threat INS-06).

    A shared key would make the second upload report "already processed" and return
    the first case's version - which tells the uploader the document is already in a
    case they may not be able to read.
    """
    conn, pipeline, case_id, actor_id = ctx
    other_case = (
        await conn.execute(
            sa.text("SELECT id FROM case_record WHERE id <> :c LIMIT 1"), {"c": case_id}
        )
    ).scalar_one()
    data = FIXTURE.read_bytes()

    first = await pipeline.run(conn, case_id=case_id, actor_id=actor_id, filename="c.pdf",
                               data=data, at=NOW)
    second = await pipeline.run(conn, case_id=other_case, actor_id=actor_id, filename="c.pdf",
                                data=data, at=NOW)
    await conn.commit()

    assert first.version_id != second.version_id

    # **The stored digests are NOT asserted equal**, and that is not a weaker test —
    # it is the only honest one. ADR 0017: `sanitise` is deterministic within a clean
    # process, and across a long-lived one its output occasionally differs by a few
    # bytes as mupdf compacts object numbering differently. Asserting equality here
    # made this file fail intermittently, in a different test each time, for a property
    # the project has documented as not guaranteed.
    #
    # What IS guaranteed, and what identity actually keys on since migration 0008, is
    # the digest of what ARRIVED. That is asserted instead.
    sources = (
        await conn.execute(
            sa.text(
                "SELECT source_sha256 FROM document_version WHERE id IN (:a, :b)"
            ),
            {"a": first.version_id, "b": second.version_id},
        )
    ).scalars().all()
    assert len(set(sources)) == 1, (
        f"the same uploaded bytes recorded different source digests: {sources}"
    )


# --- failure and retry -----------------------------------------------------------

class MissingEngine(EmbeddedTextLayer):
    """Stands in for Tesseract not being installed - the realistic OCR failure."""

    def extract(self, pdf_bytes: bytes):
        raise TextSourceUnavailable("tesseract is not installed")


async def test_a_failed_stage_records_an_enumerated_code_and_stops_the_thread(ctx):
    conn, pipeline, case_id, actor_id = ctx
    pipeline.text_source = MissingEngine()

    broken = await pipeline.run(conn, case_id=case_id, actor_id=actor_id, filename="c.pdf",
                                data=FIXTURE.read_bytes(), at=NOW)
    await conn.commit()

    failed = [s for s in broken.stages if s.status == JobStatus.FAILED]
    assert failed, f"the stage did not fail as arranged: {broken.stages}"
    assert failed[0].stage == "ocr"

    # Nothing after the failed stage ran: there is no anchor for a document whose
    # text was never read.
    assert not any(s.stage == "anchor" for s in broken.stages)

    job = (
        await conn.execute(
            sa.text(
                "SELECT attempts, status, error_code FROM processing_job "
                "WHERE document_version_id = :v AND stage = 'ocr'"
            ),
            {"v": broken.version_id},
        )
    ).mappings().one()
    assert job["status"] == JobStatus.FAILED
    assert job["attempts"] == 1
    assert job["error_code"] == "text_source_unavailable", (
        "the error column must hold an enumerated code, never exception text - a raw "
        "message carries document content back out over the job-status route (CD-01)"
    )


async def test_a_failed_stage_is_retried_and_the_attempt_is_counted(ctx):
    """"Retry count" is one of the things the reliability invariant requires recorded."""
    conn, pipeline, case_id, actor_id = ctx
    data = FIXTURE.read_bytes()

    pipeline.text_source = MissingEngine()
    broken = await pipeline.run(conn, case_id=case_id, actor_id=actor_id, filename="c.pdf",
                                data=data, at=NOW)
    await conn.commit()

    # The engine comes back; the previously failed stage must run, not be skipped.
    pipeline.text_source = EmbeddedTextLayer()
    recovered = await pipeline.run(conn, case_id=case_id, actor_id=actor_id, filename="c.pdf",
                                   data=data, at=NOW)
    await conn.commit()

    assert recovered.version_id == broken.version_id
    assert recovered.ok, [s for s in recovered.stages if s.status == JobStatus.FAILED]

    job = (
        await conn.execute(
            sa.text(
                "SELECT attempts, status FROM processing_job "
                "WHERE document_version_id = :v AND stage = 'ocr'"
            ),
            {"v": broken.version_id},
        )
    ).mappings().one()
    assert job["status"] == JobStatus.SUCCEEDED
    assert job["attempts"] == 2, (
        f"attempts recorded as {job['attempts']}; a retry that does not count itself "
        f"cannot distinguish a flaky stage from a healthy one"
    )

    # And the retry still produced exactly one of everything.
    final = await counts(conn, broken.version_id)
    assert final["ocr_text"] == 1 and final["anchors"] == 1


async def test_nothing_in_the_pipeline_writes_verified(ctx):
    """Invariant 9. Extraction produces drafts; only a human commit changes that."""
    conn, pipeline, case_id, actor_id = ctx
    result = await pipeline.run(conn, case_id=case_id, actor_id=actor_id, filename="c.pdf",
                                data=FIXTURE.read_bytes(), at=NOW)
    await conn.commit()
    statuses = (
        await conn.execute(
            sa.text("SELECT DISTINCT status FROM extracted_field WHERE version_id = :v"),
            {"v": result.version_id},
        )
    ).scalars().all()
    assert set(statuses) <= {"draft"}, f"a pipeline stage wrote {statuses}"


async def test_the_version_records_what_arrived_as_well_as_what_is_held(ctx):
    """Migration 0008, and the reason identity moved off the stored digest.

    Sanitisation sits in front of version creation, so the bytes stored are not the
    bytes received. Keying version identity on the stored digest made an upload's
    identity depend on PyMuPDF serialising identically every time for the life of the
    process — which it very nearly does, and the gap showed up as these tests failing
    intermittently in full runs and passing in isolation, in a different test each time.

    `source_sha256` is what arrived; `sha256` is what is held, signed and anchored. When
    they differ, something was removed, and before this column that difference was
    invisible.
    """
    import fitz

    from infra.blobstore import sha256_bytes

    conn, pipeline, case_id, actor_id = ctx

    doc = fitz.open()
    doc.new_page().insert_text((72, 96), "SPECIMEN - NOT A REAL RECORD", fontsize=12)
    plain = doc.tobytes()
    doc.close()
    doc = fitz.open(stream=plain, filetype="pdf")
    action = doc.get_new_xref()
    doc.update_object(action, r"<< /Type /Action /S /JavaScript /JS (app.alert\(1\);) >>")
    doc.xref_set_key(doc.pdf_catalog(), "OpenAction", f"{action} 0 R")
    hostile = doc.tobytes()
    doc.close()

    result = await pipeline.run(
        conn, case_id=case_id, actor_id=actor_id, filename="hostile.pdf", data=hostile,
    )
    row = (
        await conn.execute(
            sa.text(
                "SELECT sha256, source_sha256 FROM document_version WHERE id = :v"
            ),
            {"v": result.version_id},
        )
    ).mappings().one()

    assert row["source_sha256"] == sha256_bytes(hostile), "the upload's digest was not kept"
    assert row["sha256"] != row["source_sha256"], (
        "stored and received are identical, so sanitisation removed nothing"
    )
    assert row["sha256"] == result.content_sha256
