"""Slice 7: destructive redaction, and the leak its acceptance test does not catch.

`docs/PLAN.md` states the criterion as: extract text from the derivative and assert
the victim name is absent. That is necessary and it is not sufficient, and the threat
model says so in as many words (VIC-01):

    Redaction is modelled as a NEW VERSION. The original's OCR text, extracted field
    values and search index are untouched, so a subject restricted to the derivative
    can read the removed name from the text endpoint instead of the PDF. This is the
    most likely way the headline demo is actually defeated.

So this file asserts both halves: the bytes are clean, **and** the derived text is out
of reach for the role that only gets the derivative.
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import fitz
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from domain.subject import CaseFacts
from infra.disclosure import (
    Disclosure,
    disclosure_for,
    readable_fields,
    readable_ocr_text,
    readable_version_ids,
)
from infra.redact import Region, confirm_absent, redact

pytestmark = pytest.mark.requires_db

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "corpus" / "complaint-0001.pdf"
SIDECAR = ROOT / "fixtures" / "corpus" / "complaint-0001.json"
NOW = datetime.now(timezone.utc)


def regions_from_sidecar() -> tuple[list[Region], list[str]]:
    side = json.loads(SIDECAR.read_text(encoding="utf-8"))
    regions = [
        Region(page_no=f["page"], x0=f["bbox"][0], y0=f["bbox"][1],
               x1=f["bbox"][2], y1=f["bbox"][3], rule_id=f["label"],
               removed_text=f["value"])
        for f in side["identifying_fields"]
    ]
    return regions, [f["value"] for f in side["identifying_fields"]]


# --- the bytes ----------------------------------------------------------------

def test_the_named_values_are_absent_from_the_derivative():
    """PLAN's acceptance criterion."""
    regions, names = regions_from_sidecar()
    result = redact(FIXTURE.read_bytes(), regions)
    assert confirm_absent(result.pdf_bytes, names) == []


def test_redaction_removes_rather_than_covers():
    """A black rectangle leaves the glyphs addressable underneath (threat RED-01).

    Checked by extracting text, which is exactly what an attacker does first.
    """
    regions, names = regions_from_sidecar()
    result = redact(FIXTURE.read_bytes(), regions)
    with fitz.open(stream=result.pdf_bytes, filetype="pdf") as doc:
        extracted = "\n".join(p.get_text() for p in doc)
    for name in names:
        assert name.lower() not in extracted.lower()


def test_the_derivative_is_rasterised():
    """Rendering to pixels removes the question of what else the PDF retained."""
    regions, _ = regions_from_sidecar()
    result = redact(FIXTURE.read_bytes(), regions)
    with fitz.open(stream=result.pdf_bytes, filetype="pdf") as doc:
        assert len(doc[0].get_images()) >= 1, "the page is not an image"
        assert doc[0].get_text().strip() == "", "a text layer survived rasterisation"


def test_container_metadata_and_outline_are_cleared():
    """Metadata, XMP and outline can each carry the name independently (VIC-03)."""
    regions, names = regions_from_sidecar()
    source = fitz.open(stream=FIXTURE.read_bytes(), filetype="pdf")
    source.set_metadata({"title": names[0], "author": names[0], "subject": names[0]})
    poisoned = source.tobytes()
    source.close()

    result = redact(poisoned, regions)
    with fitz.open(stream=result.pdf_bytes, filetype="pdf") as doc:
        blob = json.dumps(doc.metadata or {}) + json.dumps(doc.get_toc() or [])
    for name in names:
        assert name.lower() not in blob.lower(), f"{name} survived in the container"


def test_the_original_is_not_mutated():
    """Originals are never overwritten or mutated (reliability invariant)."""
    before = FIXTURE.read_bytes()
    regions, names = regions_from_sidecar()
    redact(before, regions)
    assert FIXTURE.read_bytes() == before
    # And the original still contains what it always did.
    assert confirm_absent(before, names) == names


def test_refusing_to_produce_an_empty_redaction():
    """A derivative with no regions is an unredacted copy with a reassuring name."""
    with pytest.raises(ValueError):
        redact(FIXTURE.read_bytes(), [])


# --- the manifest -------------------------------------------------------------

def test_the_manifest_never_contains_the_removed_text():
    """Threat VIC-04: a manifest of removed strings is a curated list of names."""
    regions, names = regions_from_sidecar()
    result = redact(FIXTURE.read_bytes(), regions)
    blob = json.dumps(result.regions)
    for name in names:
        assert name.lower() not in blob.lower(), f"the manifest leaked {name!r}"


def test_the_manifest_records_geometry_and_rule():
    regions, _ = regions_from_sidecar()
    result = redact(FIXTURE.read_bytes(), regions)
    for entry in result.regions:
        assert {"page_no", "x0", "y0", "x1", "y1", "rule_id", "removed_hash"} == entry.keys()
        assert entry["rule_id"]


def test_the_same_name_hashes_differently_in_two_manifests():
    """Per-manifest salt, so manifests cannot be cross-referenced into a name list."""
    regions, _ = regions_from_sidecar()
    a = redact(FIXTURE.read_bytes(), regions)
    b = redact(FIXTURE.read_bytes(), regions)
    assert a.salt != b.salt
    assert a.regions[0]["removed_hash"] != b.regions[0]["removed_hash"]


def test_a_known_name_can_still_be_checked_against_the_manifest():
    """The hash is useless for discovery and useful for confirmation, by design."""
    import hashlib

    regions, names = regions_from_sidecar()
    result = redact(FIXTURE.read_bytes(), regions)
    expected = hashlib.sha256(f"{result.salt}|{names[0]}".encode()).hexdigest()
    assert any(r["removed_hash"] == expected for r in result.regions)


# --- disclosure: the half PLAN's criterion misses ------------------------------

def facts(**overrides) -> CaseFacts:
    base = dict(case_id="c1", organization_id="o1", jurisdiction_id="j1", is_sealed=False)
    return CaseFacts(**{**base, **overrides})


def test_a_designated_officer_gets_the_original():
    decision = disclosure_for(subject=None, case=facts(assignment_active=True))
    assert decision.disclosure is Disclosure.ORIGINAL


def test_a_grantee_gets_the_redacted_copy_only():
    decision = disclosure_for(subject=None, case=facts(grant_active=True))
    assert decision.disclosure is Disclosure.REDACTED
    assert not decision.may_read_original


def test_a_self_issued_grant_discloses_nothing():
    decision = disclosure_for(
        subject=None, case=facts(grant_active=True, grant_is_self_issued=True)
    )
    assert decision.disclosure is Disclosure.NONE


def test_no_route_discloses_nothing():
    assert disclosure_for(subject=None, case=facts()).disclosure is Disclosure.NONE


def test_rank_is_not_an_input():
    """Seniority does not widen disclosure; only designation and grant do."""
    assert (
        disclosure_for(subject=None, case=facts(assignment_active=True)).disclosure
        is disclosure_for(subject=None, case=facts(assignment_active=True)).disclosure
    )


# --- VIC-01, against the database ---------------------------------------------

@pytest.fixture
async def ctx(live_settings, tmp_path):
    """A document with OCR text and extracted fields, plus a redacted derivative."""
    import seed as seed_module
    from infra.anchor import LocalAnchorStore
    from infra.blobstore import LocalBlobStore
    from infra.esign import SimulatedESignProvider
    from infra.pipeline import Pipeline
    from infra.textsource import EmbeddedTextLayer

    await seed_module.seed()
    engine = create_async_engine(live_settings.owner_dsn)
    blobs = LocalBlobStore(tmp_path / "blobs")
    pipeline = Pipeline(blobs=blobs, text_source=EmbeddedTextLayer(),
                        signer=SimulatedESignProvider("s"), anchors=LocalAnchorStore())

    async with engine.connect() as conn:
        case_id = (await conn.execute(sa.text("SELECT id FROM case_record LIMIT 1"))).scalar_one()
        actor_id = (await conn.execute(sa.text("SELECT id FROM app_user LIMIT 1"))).scalar_one()
        run = await pipeline.run(conn, case_id=case_id, actor_id=actor_id,
                                 filename="complaint.pdf", data=FIXTURE.read_bytes(), at=NOW)

        regions, names = regions_from_sidecar()
        result = redact(FIXTURE.read_bytes(), regions)
        derivative_sha = blobs.put(result.pdf_bytes)
        derivative_id = uuid.uuid4()
        await conn.execute(
            sa.text(
                "INSERT INTO document_version (id, document_id, version_no, sha256, "
                " derived_from_version_id, redaction_manifest_hash) "
                "VALUES (:i,:d,2,:h,:parent,:m)"
            ),
            {"i": derivative_id, "d": run.document_id, "h": derivative_sha,
             "parent": run.version_id, "m": result.manifest_hash},
        )
        await conn.commit()
        yield conn, {"document_id": run.document_id, "parent_id": run.version_id,
                     "derivative_id": str(derivative_id), "names": names}
    await engine.dispose()


async def test_the_derivative_is_a_first_class_version(ctx):
    conn, ids = ctx
    row = (
        await conn.execute(
            sa.text(
                "SELECT sha256, derived_from_version_id, redaction_manifest_hash "
                "FROM document_version WHERE id = :i"
            ),
            {"i": ids["derivative_id"]},
        )
    ).mappings().one()
    assert row["derived_from_version_id"] is not None
    assert row["redaction_manifest_hash"]
    parent_sha = (
        await conn.execute(
            sa.text("SELECT sha256 FROM document_version WHERE id = :i"),
            {"i": ids["parent_id"]},
        )
    ).scalar_one()
    assert row["sha256"] != parent_sha, "the derivative has its own digest"


async def test_a_redacted_role_cannot_read_the_parent_version(ctx):
    """Threat INS-08: derived_from_version_id is handed to the client by design."""
    conn, ids = ctx
    allowed = await readable_version_ids(
        conn, document_id=ids["document_id"], disclosure=Disclosure.REDACTED
    )
    assert ids["derivative_id"] in allowed
    assert str(ids["parent_id"]) not in allowed, (
        "the redacted role can request the parent version id directly"
    )


async def test_a_redacted_role_cannot_read_the_originals_ocr_text(ctx):
    """VIC-01. The leak PLAN's acceptance criterion does not catch.

    The PDF is clean and the name is still sitting in ocr_text, which redaction never
    touched because it produced a new version.
    """
    conn, ids = ctx

    # The text genuinely still contains the names - this is not a vacuous test.
    raw = await readable_ocr_text(conn, version_id=ids["parent_id"],
                                  disclosure=Disclosure.ORIGINAL)
    assert raw and any(n.lower() in raw.lower() for n in ids["names"]), (
        "the original's OCR text does not contain the names, so this proves nothing"
    )

    denied = await readable_ocr_text(conn, version_id=ids["parent_id"],
                                     disclosure=Disclosure.REDACTED)
    assert denied is None, "a redacted role read the unredacted OCR text"


async def test_a_redacted_role_cannot_read_the_extracted_field_values(ctx):
    """The same leak in a different shape - the values are field rows too."""
    conn, ids = ctx
    full = await readable_fields(conn, version_id=ids["parent_id"],
                                 disclosure=Disclosure.ORIGINAL)
    assert full, "no fields extracted, so this proves nothing"

    denied = await readable_fields(conn, version_id=ids["parent_id"],
                                   disclosure=Disclosure.REDACTED)
    assert denied == [], "a redacted role read the extracted field values"


async def test_the_designated_officer_still_gets_everything(ctx):
    """The control must not be a blanket denial - the investigator works the original."""
    conn, ids = ctx
    text = await readable_ocr_text(conn, version_id=ids["parent_id"],
                                   disclosure=Disclosure.ORIGINAL)
    versions = await readable_version_ids(conn, document_id=ids["document_id"],
                                          disclosure=Disclosure.ORIGINAL)
    assert text and len(versions) == 2
