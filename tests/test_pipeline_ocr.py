"""The golden thread with real OCR.

`test_pipeline_idempotency.py` uses the text layer because it counts rows. This file
runs the same thread through **Tesseract over a rasterised page**, because that is the
path that actually ships and the one docs/adr/0012 argues for.

It also asserts the honesty properties that make slice 11a's accuracy figure mean
something: the recorded method is `tesseract_ocr`, the provider and model are real,
and nothing silently substituted the embedded text layer.
"""
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from domain.extraction import span_to_boxes
from infra.anchor import LocalAnchorStore
from infra.blobstore import LocalBlobStore
from infra.esign import SimulatedESignProvider
from infra.pipeline import Pipeline
from infra.textsource import TesseractOcr

pytestmark = pytest.mark.requires_db

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "corpus" / "complaint-0001.pdf"
NOW = datetime.now(timezone.utc)

pytestmark = [
    pytest.mark.requires_db,
    pytest.mark.skipif(not TesseractOcr.available(), reason="tesseract is not installed"),
]


@pytest.fixture
async def ran(live_settings, tmp_path):
    import seed as seed_module

    await seed_module.seed()
    engine = create_async_engine(live_settings.owner_dsn)
    pipeline = Pipeline(
        blobs=LocalBlobStore(tmp_path / "blobs"),
        text_source=TesseractOcr(languages="eng"),
        signer=SimulatedESignProvider("test-secret"),
        anchors=LocalAnchorStore(),
    )
    async with engine.connect() as conn:
        case_id = (await conn.execute(sa.text("SELECT id FROM case_record LIMIT 1"))).scalar_one()
        actor_id = (await conn.execute(sa.text("SELECT id FROM app_user LIMIT 1"))).scalar_one()
        result = await pipeline.run(
            conn, case_id=case_id, actor_id=actor_id, filename="complaint.pdf",
            data=FIXTURE.read_bytes(), at=NOW,
        )
        await conn.commit()
        yield conn, result
    await engine.dispose()


async def test_the_whole_thread_succeeds(ran):
    conn, result = ran
    failed = [s for s in result.stages if s.status == "failed"]
    assert not failed, failed
    assert {s.stage for s in result.stages} == {"ocr", "extract", "sign", "anchor"}


async def test_the_recorded_method_is_ocr_not_the_text_layer(ran):
    """docs/adr/0012. If this ever says embedded_text_layer, slice 11a's CER is void."""
    conn, result = ran
    row = (
        await conn.execute(
            sa.text(
                "SELECT method, provider, model, mean_confidence "
                "FROM ocr_text WHERE version_id = :v"
            ),
            {"v": result.version_id},
        )
    ).mappings().one()
    assert row["method"] == "tesseract_ocr"
    assert row["provider"] == "tesseract"
    assert "tesseract" in row["model"].lower(), row["model"]
    assert row["mean_confidence"] is not None and row["mean_confidence"] > 0


async def test_ocr_produced_word_boxes_with_spans(ran):
    """The char-offset-to-bbox map slice 5b and slice 7 both depend on."""
    conn, result = ran
    words = (
        await conn.execute(
            sa.text(
                "SELECT char_start, char_end, x0, y0, x1, y1 FROM ocr_word "
                "WHERE version_id = :v ORDER BY char_start"
            ),
            {"v": result.version_id},
        )
    ).mappings().all()
    assert len(words) > 20
    for w in words:
        assert w["char_end"] > w["char_start"]
        assert w["x1"] > w["x0"] and w["y1"] > w["y0"]


async def test_every_extracted_field_points_at_text_that_contains_its_value(ran):
    """The provenance chain, end to end: field -> span -> OCR text -> the value.

    This is what makes an extracted field evidence rather than an assertion, and it is
    the property slice 5b's highlight and slice 7's redaction both rely on.
    """
    conn, result = ran
    text = (
        await conn.execute(
            sa.text("SELECT text FROM ocr_text WHERE version_id = :v"),
            {"v": result.version_id},
        )
    ).scalar_one()
    fields = (
        await conn.execute(
            sa.text(
                "SELECT field_key, value, source_span_start, source_span_end "
                "FROM extracted_field WHERE version_id = :v"
            ),
            {"v": result.version_id},
        )
    ).mappings().all()

    assert fields, "real OCR produced no extractable fields"
    for f in fields:
        sliced = text[f["source_span_start"]:f["source_span_end"]]
        assert sliced == f["value"], (
            f"{f['field_key']}: span points at {sliced!r}, field says {f['value']!r} - "
            f"an off-by-one here aims redaction at the wrong pixels"
        )


async def test_a_field_span_maps_to_boxes_on_the_page(ran):
    conn, result = ran
    from infra.textsource import Word

    rows = (
        await conn.execute(
            sa.text(
                "SELECT char_start, char_end, x0, y0, x1, y1, confidence, page_no "
                "FROM ocr_word WHERE version_id = :v"
            ),
            {"v": result.version_id},
        )
    ).mappings().all()
    words = [
        Word(text="", char_start=r["char_start"], char_end=r["char_end"], x0=r["x0"],
             y0=r["y0"], x1=r["x1"], y1=r["y1"], confidence=r["confidence"],
             page_no=r["page_no"])
        for r in rows
    ]
    field = (
        await conn.execute(
            sa.text(
                "SELECT source_span_start, source_span_end FROM extracted_field "
                "WHERE version_id = :v LIMIT 1"
            ),
            {"v": result.version_id},
        )
    ).mappings().one()
    boxes = span_to_boxes(words, field["source_span_start"], field["source_span_end"])
    assert boxes, "a field's span mapped to no rectangle on the page"


async def test_the_anchor_matches_the_stored_digest(ran):
    conn, result = ran
    anchored = (
        await conn.execute(
            sa.text("SELECT content_sha256 FROM anchor_record WHERE version_id = :v"),
            {"v": result.version_id},
        )
    ).scalar_one()
    assert anchored == result.content_sha256
