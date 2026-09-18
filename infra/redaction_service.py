"""Turning a redaction into a version.

Slice 7 built the operation — remove, rasterise, rebuild — and nothing that persists
its result. The algorithm was reachable from a test and from a Sentinel scenario that
wrote the rows by hand, which is why the derivative existed in the database with a
placeholder digest and no bytes behind it for several sessions without anyone noticing.
A capability with no persistence path is a capability the product does not have.

**Regions come from the fields, not from a mouse.** The caller names extracted fields;
this resolves each one to the OCR word boxes its character span covers, which is the
same mapping slice 5b+ draws on the screen. That has two consequences worth stating:

  The redaction covers exactly what the operator saw highlighted. There is no second
  coordinate system to disagree with the first.

  **It can only cover what OCR located.** A name the engine misread is a name with no
  word boxes and therefore no rectangle — accepted risk AR-6, and now with a number
  against it, because slice 6b measured 27% character error on degraded scans. On a
  poor scan, field-driven redaction is materially less reliable, and the manifest
  records what was removed rather than implying that everything identifying was.

The manifest never stores removed text — only geometry, a rule id and a per-manifest
salted hash (ADR 0009's reasoning, and threat VIC-04).
"""
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa

from domain.enums import AuditAction
from infra.audit_log import append_audit
from infra.blobstore import BlobStore
from infra.redact import Region, redact


class RedactionUnavailable(RuntimeError):
    """Raised when nothing could be located to remove. Never a silent no-op."""


async def regions_for_fields(conn, *, version_id: str, field_ids: list[str]) -> list[Region]:
    """Resolve each field's character span to the OCR word boxes it covers."""
    if not field_ids:
        return []

    rows = (
        await conn.execute(
            sa.text(
                "SELECT f.id, f.field_key, f.value, f.source_span_start, f.source_span_end "
                "FROM extracted_field f WHERE f.version_id = :v AND f.id IN :ids"
            ).bindparams(sa.bindparam("ids", expanding=True)),
            {"v": version_id, "ids": [uuid.UUID(f) for f in field_ids]},
        )
    ).mappings().all()

    regions: list[Region] = []
    for row in rows:
        if row["source_span_start"] is None:
            # A hand-entered value has no span into the OCR text, so there is no
            # rectangle to burn. Skipped rather than approximated: a box in the wrong
            # place is worse than no box, because it looks like the name was covered.
            continue
        words = (
            await conn.execute(
                sa.text(
                    "SELECT page_no, x0, y0, x1, y1 FROM ocr_word "
                    "WHERE version_id = :v AND char_end > :s AND char_start < :e"
                ),
                {"v": version_id, "s": row["source_span_start"], "e": row["source_span_end"]},
            )
        ).mappings().all()
        for word in words:
            regions.append(
                Region(
                    page_no=word["page_no"],
                    x0=word["x0"], y0=word["y0"], x1=word["x1"], y1=word["y1"],
                    rule_id=row["field_key"],
                    removed_text=row["value"],
                )
            )
    return regions


async def create_redacted_version(
    conn,
    blobs: BlobStore,
    *,
    parent_version_id: str,
    case_id: str,
    field_ids: list[str],
    actor_id: str,
    at: datetime | None = None,
) -> dict:
    """Produce the derivative, store it, and record what was removed.

    Idempotent by content: the derivative is content-addressed like any other version,
    so redacting the same fields twice finds the existing derivative rather than
    stacking a second one.
    """
    at = at or datetime.now(timezone.utc)

    parent = (
        await conn.execute(
            sa.text(
                "SELECT dv.id, dv.document_id, dv.sha256, dv.version_no "
                "FROM document_version dv WHERE dv.id = :v"
            ),
            {"v": parent_version_id},
        )
    ).mappings().one_or_none()
    if parent is None:
        raise RedactionUnavailable("no such version")

    source = blobs.get(parent["sha256"])
    if source is None:
        raise RedactionUnavailable("the original bytes are not in the store")

    regions = await regions_for_fields(
        conn, version_id=parent_version_id, field_ids=field_ids
    )
    if not regions:
        # Refusing beats producing a "redacted" copy identical to the original, which
        # would be handed to a grantee as though something had been removed.
        raise RedactionUnavailable("nothing locatable to remove")

    # **Not deduplicated by content.** `redact()` draws a fresh random salt for every
    # manifest, so the same request twice produces different bytes and a different
    # digest — content-addressing cannot see that they are the same redaction. The
    # obvious fix, deriving the salt from the document, is the wrong one: the salt's
    # whole job is to stop a removed-value hash being correlated between documents,
    # and that is a security property, not an implementation detail.
    #
    # So the match is on *what was redacted* rather than on the resulting bytes: an
    # existing derivative of this parent whose manifest covers exactly the same rule
    # ids is this redaction, already done. Machine-extracted values never change after
    # extraction, so the same rule set over the same parent means the same regions.
    rules = sorted({r.rule_id for r in regions})
    duplicate = (
        await conn.execute(
            sa.text(
                "SELECT m.derivative_version_id FROM redaction_manifest m "
                "WHERE m.parent_version_id = :p "
                "  AND (SELECT array_agg(DISTINCT rr.rule_id ORDER BY rr.rule_id) "
                "       FROM redaction_region rr WHERE rr.manifest_id = m.id) = :rules "
                "LIMIT 1"
            ).bindparams(sa.bindparam("rules", type_=sa.ARRAY(sa.Text()))),
            {"p": parent_version_id, "rules": rules},
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        return {"version_id": str(duplicate), "regions": len(regions), "created": False}

    result = redact(source, regions)
    derivative_sha = blobs.put(result.pdf_bytes)

    next_no = (
        await conn.execute(
            sa.text(
                "SELECT COALESCE(MAX(version_no), 0) + 1 FROM document_version "
                "WHERE document_id = :d"
            ),
            {"d": parent["document_id"]},
        )
    ).scalar_one()

    derivative_id = uuid.uuid4()
    await conn.execute(
        sa.text(
            "INSERT INTO document_version (id, document_id, version_no, sha256, "
            " derived_from_version_id, redaction_manifest_hash) "
            "VALUES (:i,:d,:n,:h,:p,:m)"
        ),
        {"i": derivative_id, "d": parent["document_id"], "n": next_no,
         "h": derivative_sha, "p": parent_version_id, "m": result.manifest_hash},
    )

    manifest_id = uuid.uuid4()
    await conn.execute(
        sa.text(
            "INSERT INTO redaction_manifest (id, derivative_version_id, "
            " parent_version_id, case_id, salt, manifest_hash, created_by) "
            "VALUES (:i,:d,:p,:c,:s,:h,:u)"
        ),
        {"i": manifest_id, "d": derivative_id, "p": parent_version_id, "c": case_id,
         "s": result.salt, "h": result.manifest_hash, "u": actor_id},
    )
    for record in result.regions:
        await conn.execute(
            sa.text(
                "INSERT INTO redaction_region (manifest_id, page_no, x0, y0, x1, y1, "
                " rule_id, removed_hash) VALUES (:m,:pg,:x0,:y0,:x1,:y1,:r,:h)"
            ),
            {"m": manifest_id, "pg": record["page_no"], "x0": record["x0"],
             "y0": record["y0"], "x1": record["x1"], "y1": record["y1"],
             "r": record["rule_id"], "h": record["removed_hash"]},
        )

    await append_audit(
        conn,
        case_id=case_id,
        actor_id=actor_id,
        action=AuditAction.VERSION_CREATED,
        object_type="document_version",
        object_id=str(derivative_id),
        at=at,
    )
    return {"version_id": str(derivative_id), "regions": len(regions), "created": True}
