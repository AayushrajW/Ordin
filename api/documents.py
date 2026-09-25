"""Document, version and field routes — the surface slice 5b's screens read and write.

**Two checks, not one.** Every route here resolves the case and asks slice 3 "may this
subject read this case at all?", and then asks `infra/disclosure.py` "which version do
they get?". Collapsing those into one check is the mistake this file exists to avoid:
a purpose-limited grantee passes the first and must fail the second, and the gap
between them is threat VIC-01.

**Writing is narrower than reading.** Reading is gated by the disclosure class, so a
grantee reads derivatives. Verifying is gated by disclosure ORIGINAL, because
verification is an attestation about the contents of the original document and a
subject forbidden to read it cannot make that claim (docs/adr/0014).

Denied and nonexistent are the same 404 throughout, byte for byte, for the same reason
`api/cases.py` says: a distinguishable response is an existence oracle over guessable
ids (threat INS-04). That is asserted, not assumed —
`test_an_unreadable_case_and_a_missing_one_are_byte_identical`.
"""
import logging
import re
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from api.deps import policy as get_policy
from api.deps import require_subject
from domain.enums import AuditAction
from domain.policy import Policy
from domain.subject import Subject
from infra.audit_log import append_audit
from infra.authz import decide, load_case_facts
from infra.decisions import record_decision
from infra.crypto import DecryptionFailed
from infra.disclosure import (
    Disclosure,
    disclosure_for,
    readable_ocr_text,
    readable_version_ids,
)
from infra.logging_context import current_correlation_id

# Mirrors the check constraint in migration 0012. Both exist: the constraint is
# the control, this is the good error message.
DOC_CLASSES = (
    "fir", "statement", "forensic_report", "charge_sheet", "court_order", "other",
)

log = logging.getLogger("ordin.api.documents")
router = APIRouter(tags=["documents"])

# Rendered at 2x for a legible scan on a laptop screen without shipping a 4 MB PNG.
PAGE_ZOOM = 2.0

NOT_FOUND = HTTPException(status_code=404, detail="not_found")


class DocumentOut(BaseModel):
    id: str
    title: str
    disclosure: str
    case_id: str | None = None
    versions: list["VersionOut"] = []


class VersionOut(BaseModel):
    id: str
    version_no: int
    sha256: str
    lifecycle_state: str
    is_derivative: bool


class FieldOut(BaseModel):
    id: str
    field_key: str
    value: str
    status: str
    source: str
    confidence: float | None = None
    source_span_start: int | None = None
    source_span_end: int | None = None
    provider: str | None = None
    model: str | None = None
    verified_by: str | None = None
    entered_by: str | None = None
    # The OCR engine's own confidence in the words this value was read from — the
    # lowest of them. `confidence` above is the pattern's, which is always 1.0 for a
    # deterministic match and says nothing about whether the text was read correctly.
    ocr_confidence: float | None = None
    # A machine draft for which a person has since recorded a value under the same
    # key. It is kept - it is the record of what the extractor read - but it is no
    # longer awaiting anyone, and must not be counted or flagged as though it were.
    superseded: bool = False
    anomalies: list["AnomalyOut"] = []


class AnomalyOut(BaseModel):
    code: str
    severity: str
    message: str
    suggestion: str | None = None


class FieldEntry(BaseModel):
    """A value a human typed. No span, and none is invented for it (ADR 0011)."""

    field_key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    value: str = Field(min_length=1, max_length=512)


class Box(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class SpanOut(BaseModel):
    page_no: int
    page_width: float
    page_height: float
    boxes: list[Box]


DocumentOut.model_rebuild()
FieldOut.model_rebuild()


# --- resolution ---------------------------------------------------------------


class IntegrityMismatch(Exception):
    """The stored bytes are not the bytes that were stored."""


def _read_blob(blobs, sha256: str) -> bytes | None:
    """Stored bytes, or None when they are absent.

    Raises `IntegrityMismatch` when the blob is present and will not open. With
    encryption (ADR 0028) that is what tampering looks like: AES-GCM authenticates, so
    a flipped bit fails the tag rather than returning altered bytes for a digest
    comparison to catch. Same meaning, earlier signal — and the caller must not
    confuse it with "missing", because a document that is present and altered is the
    one thing this system exists to notice.
    """
    try:
        return blobs.get(sha256)
    except DecryptionFailed as exc:
        raise IntegrityMismatch from exc


async def _case_disclosure(conn, policy: Policy, subject: Subject, case_id, at: datetime):
    """The two checks, in order, or 404.

    Returns the disclosure class. Raises the shared 404 for "no such case", "not
    permitted" and "permitted but no disclosure route" alike.
    """
    decision = await decide(conn, policy, subject, str(case_id), at)
    await record_decision(
        conn,
        decision,
        subject=subject,
        resource_type="case",
        resource_id=str(case_id),
        correlation_id=current_correlation_id(),
    )
    if not decision.allowed:
        raise NOT_FOUND

    facts = await load_case_facts(conn, subject, str(case_id), at)
    if facts is None:
        raise NOT_FOUND
    disclosure = disclosure_for(subject, facts).disclosure
    if disclosure is Disclosure.NONE:
        raise NOT_FOUND
    return disclosure


async def _resolve_version(conn, policy: Policy, subject: Subject, version_id: str, at: datetime):
    """version -> (document_id, case_id, disclosure), refusing anything not readable.

    The membership test against `readable_version_ids` is what stops a grantee naming
    the parent version id that their own derivative openly references (threat INS-08).
    """
    try:
        uuid.UUID(str(version_id))
    except ValueError:
        raise NOT_FOUND

    row = (
        await conn.execute(
            sa.text(
                "SELECT dv.id, dv.document_id, d.case_id FROM document_version dv "
                "JOIN document d ON d.id = dv.document_id WHERE dv.id = :v"
            ),
            {"v": version_id},
        )
    ).mappings().one_or_none()
    if row is None:
        raise NOT_FOUND

    disclosure = await _case_disclosure(conn, policy, subject, row["case_id"], at)
    allowed = await readable_version_ids(
        conn, document_id=str(row["document_id"]), disclosure=disclosure
    )
    if str(version_id) not in allowed:
        raise NOT_FOUND
    return str(row["document_id"]), str(row["case_id"]), disclosure


async def _resolve_field(conn, policy: Policy, subject: Subject, field_id: str, at: datetime):
    try:
        uuid.UUID(str(field_id))
    except ValueError:
        raise NOT_FOUND

    row = (
        await conn.execute(
            sa.text(
                "SELECT id, version_id, case_id, field_key, value, status, source, "
                "       source_span_start, source_span_end, verified_by "
                "FROM extracted_field WHERE id = :f"
            ),
            {"f": field_id},
        )
    ).mappings().one_or_none()
    if row is None:
        raise NOT_FOUND
    _, _, disclosure = await _resolve_version(
        conn, policy, subject, str(row["version_id"]), at
    )
    return row, disclosure


def _require_original(disclosure: Disclosure) -> None:
    """ADR 0014. Attesting to a document you may not read is not a thing to allow."""
    if disclosure is not Disclosure.ORIGINAL:
        raise NOT_FOUND


# --- reading ------------------------------------------------------------------


@router.get("/cases/{case_id}/documents")
async def list_documents(
    case_id: str,
    request: Request,
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
) -> list[DocumentOut]:
    now = datetime.now(timezone.utc)
    try:
        uuid.UUID(case_id)
    except ValueError:
        raise NOT_FOUND

    async with request.app.state.engine.connect() as conn:
        disclosure = await _case_disclosure(conn, policy, subject, case_id, now)
        await conn.commit()

        documents = (
            await conn.execute(
                sa.text("SELECT id, title FROM document WHERE case_id = :c ORDER BY title"),
                {"c": case_id},
            )
        ).mappings().all()

        out: list[DocumentOut] = []
        for d in documents:
            version_ids = await readable_version_ids(
                conn, document_id=str(d["id"]), disclosure=disclosure
            )
            if not version_ids:
                # A document with nothing this subject may receive is not listed at
                # all. Listing it with an empty version set would confirm it exists.
                continue
            out.append(
                DocumentOut(
                    id=str(d["id"]),
                    title=d["title"],
                    disclosure=disclosure.value,
                    case_id=case_id,
                    versions=await _versions(conn, version_ids),
                )
            )
    return out


async def _versions(conn, version_ids: list[str]) -> list[VersionOut]:
    rows = (
        await conn.execute(
            sa.text(
                "SELECT id, version_no, sha256, lifecycle_state, "
                "       derived_from_version_id IS NOT NULL AS is_derivative "
                "FROM document_version WHERE id IN :ids ORDER BY version_no"
            ).bindparams(sa.bindparam("ids", expanding=True)),
            {"ids": [uuid.UUID(v) for v in version_ids]},
        )
    ).mappings().all()
    return [
        VersionOut(
            id=str(r["id"]),
            version_no=r["version_no"],
            sha256=r["sha256"],
            lifecycle_state=r["lifecycle_state"],
            is_derivative=r["is_derivative"],
        )
        for r in rows
    ]


@router.get("/documents/{document_id}")
async def get_document(
    document_id: str,
    request: Request,
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
) -> DocumentOut:
    now = datetime.now(timezone.utc)
    try:
        uuid.UUID(document_id)
    except ValueError:
        raise NOT_FOUND

    async with request.app.state.engine.connect() as conn:
        row = (
            await conn.execute(
                sa.text("SELECT id, case_id, title FROM document WHERE id = :d"),
                {"d": document_id},
            )
        ).mappings().one_or_none()
        if row is None:
            raise NOT_FOUND
        disclosure = await _case_disclosure(conn, policy, subject, row["case_id"], now)
        await conn.commit()

        version_ids = await readable_version_ids(
            conn, document_id=document_id, disclosure=disclosure
        )
        if not version_ids:
            raise NOT_FOUND
        return DocumentOut(
            id=str(row["id"]),
            title=row["title"],
            disclosure=disclosure.value,
            case_id=str(row["case_id"]),
            versions=await _versions(conn, version_ids),
        )


@router.get("/versions/{version_id}/fields")
async def version_fields(
    version_id: str,
    request: Request,
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
) -> list[FieldOut]:
    """Fields, each with the OCR engine's confidence and any consistency anomalies.

    `_resolve_version` is the gate, and a stronger one than `readable_fields`: it
    refuses the version itself unless it is in the subject's readable set, so reaching
    the select below means the version is disclosable.

    The anomalies are questions for the human, never corrections (invariant 9). The
    reference check compares against the case the document is *filed in*, which the
    subject can already read — so it discloses nothing new.
    """
    from domain.consistency import check_field

    now = datetime.now(timezone.utc)
    async with request.app.state.engine.connect() as conn:
        await _resolve_version(conn, policy, subject, version_id, now)
        await conn.commit()
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT id, field_key, value, status, source, confidence, "
                    "       source_span_start, source_span_end, provider, model, "
                    "       verified_by, entered_by "
                    "FROM extracted_field WHERE version_id = :v "
                    "ORDER BY field_key, source"
                ),
                {"v": version_id},
            )
        ).mappings().all()
        case_reference = (
            await conn.execute(
                sa.text(
                    "SELECT c.reference FROM document_version dv "
                    "JOIN document d ON d.id = dv.document_id "
                    "JOIN case_record c ON c.id = d.case_id WHERE dv.id = :v"
                ),
                {"v": version_id},
            )
        ).scalar_one_or_none()
        words = (
            await conn.execute(
                sa.text(
                    "SELECT char_start, char_end, confidence FROM ocr_word "
                    "WHERE version_id = :v AND confidence IS NOT NULL"
                ),
                {"v": version_id},
            )
        ).mappings().all()

    def lowest(start, end) -> float | None:
        if start is None or end is None:
            return None
        scores = [w["confidence"] for w in words if w["char_start"] < end and w["char_end"] > start]
        return min(scores) if scores else None

    human_keys = {r["field_key"] for r in rows if r["source"] == "human"}
    out: list[FieldOut] = []
    for r in rows:
        superseded = r["source"] != "human" and r["field_key"] in human_keys
        ocr_confidence = lowest(r["source_span_start"], r["source_span_end"])
        anomalies = []
        if r["status"] == "draft" and r["source"] != "human" and not superseded:
            anomalies = [
                AnomalyOut(code=a.code, severity=a.severity.value, message=a.message,
                           suggestion=a.suggestion)
                for a in check_field(r["field_key"], r["value"],
                                     case_reference=case_reference,
                                     word_confidence=ocr_confidence)
            ]
        out.append(FieldOut(
            id=str(r["id"]),
            field_key=r["field_key"],
            value=r["value"],
            status=r["status"],
            source=r["source"],
            confidence=r["confidence"],
            source_span_start=r["source_span_start"],
            source_span_end=r["source_span_end"],
            provider=r["provider"],
            model=r["model"],
            verified_by=str(r["verified_by"]) if r["verified_by"] else None,
            entered_by=str(r["entered_by"]) if r["entered_by"] else None,
            ocr_confidence=ocr_confidence,
            anomalies=anomalies,
            superseded=superseded,
        ))
    return out


@router.get("/versions/{version_id}/text")
async def version_text(
    version_id: str,
    request: Request,
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
):
    """OCR text, through `readable_ocr_text` rather than a direct select.

    The gate lives in `infra/disclosure.py` so this route cannot be the place someone
    forgets it. Text is returned as data and never interpreted: invariant 6.
    """
    now = datetime.now(timezone.utc)
    async with request.app.state.engine.connect() as conn:
        _, _, disclosure = await _resolve_version(conn, policy, subject, version_id, now)
        await conn.commit()
        # The real disclosure class, not a constant. `_resolve_version` has already
        # restricted which versions are reachable, so passing ORIGINAL here would
        # currently be equivalent - and would stop being equivalent the first time
        # someone widened the resolver, silently.
        text = await readable_ocr_text(conn, version_id=version_id, disclosure=disclosure)
        row = (
            await conn.execute(
                sa.text(
                    "SELECT method, provider, mean_confidence, requires_manual_entry "
                    "FROM ocr_text WHERE version_id = :v"
                ),
                {"v": version_id},
            )
        ).mappings().one_or_none()
    return {
        "text": text,
        "method": row["method"] if row else None,
        "provider": row["provider"] if row else None,
        "mean_confidence": row["mean_confidence"] if row else None,
        "requires_manual_entry": bool(row["requires_manual_entry"]) if row else False,
    }


def _watermark(page, *, viewer: str, stamp: str) -> None:
    """Burn the viewer's identity into the rendered page.

    A rendered page is the easiest thing in the system to exfiltrate: a screenshot
    leaves no trace in any log. A diagonal tiling of who rendered it and when turns an
    anonymous leak into an attributable one, which is the deterrent. It is drawn on an
    in-memory copy; the stored evidence is never touched.

    Honest about what it is: a visible watermark, not a steganographic or cryptographic
    one. It deters and attributes; it does not survive someone determined to crop it.
    """
    import fitz

    label = f"{viewer}  -  {stamp}"
    rect = page.rect
    y = -rect.height * 0.2
    while y < rect.height * 1.2:
        x = -rect.width * 0.3
        while x < rect.width * 1.1:
            pivot = fitz.Point(x, y)
            page.insert_text(
                pivot, label, fontsize=9, fontname="helv", color=(0.12, 0.16, 0.30),
                fill_opacity=0.10, morph=(pivot, fitz.Matrix(-28)),
            )
            x += 250
        y += 120
    # A legible strip at the foot, so the attribution survives a crop of the body.
    strip = fitz.Rect(0, rect.height - 16, rect.width, rect.height)
    page.draw_rect(strip, color=None, fill=(0.06, 0.09, 0.16), fill_opacity=0.85)
    page.insert_text(
        fitz.Point(10, rect.height - 5),
        f"Rendered for {label}  -  specimen environment  -  do not distribute",
        fontsize=6.5, fontname="helv", color=(1, 1, 1),
    )


@router.get("/versions/{version_id}/pages")
async def version_pages(
    version_id: str,
    request: Request,
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
):
    """How many pages this version has.

    The viewer needs it to offer navigation. Before this endpoint existed the page
    number was whatever the selected field's span happened to sit on, defaulting to
    zero - so a two-hundred page charge sheet showed page one and nothing said there
    were a hundred and ninety-nine more. The document was in the system and unreadable
    through the product.

    **Deliberately not an audit row.** `page.png` writes `document_viewed` because
    access to an original is itself evidence; a count of pages is not content and
    logging it would put a row on the chain for a request that showed nobody anything.

    Gated exactly as `page.png` is, through `_resolve_version`, so a caller learns the
    length only of a version they may already render. Reads the blob rather than a
    stored column: a page count in the database would be a second copy of a fact that
    lives in the bytes, and the two would disagree the first time one was wrong.
    """
    import fitz  # PyMuPDF. Imported here so the module loads without it for unit tests.

    now = datetime.now(timezone.utc)
    async with request.app.state.engine.connect() as conn:
        await _resolve_version(conn, policy, subject, version_id, now)
        row = (
            await conn.execute(
                sa.text(
                    "SELECT sha256, lifecycle_state FROM document_version WHERE id = :v"
                ),
                {"v": version_id},
            )
        ).mappings().one()
        await conn.commit()

    if row["lifecycle_state"] == "disposed":
        # Lawfully destroyed, so there are no bytes to count and that is not an error.
        return {"page_count": 0, "reason": "disposed"}

    try:
        data = _read_blob(request.app.state.blobs, row["sha256"])
    except IntegrityMismatch:
        raise HTTPException(status_code=409, detail="integrity_mismatch") from None
    if data is None:
        raise HTTPException(status_code=409, detail="bytes_unavailable")

    with fitz.open(stream=data, filetype="pdf") as doc:
        return {"page_count": doc.page_count}


@router.get("/versions/{version_id}/page.png")
async def version_page(
    version_id: str,
    request: Request,
    page: int = 0,
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
) -> Response:
    """The scan, rendered server-side, verified, watermarked and logged.

    **Rendered rather than served as a PDF.** A PDF handed to the browser is executed by
    a viewer, and for a derivative it would ship whatever the container still holds.

    **Verified on every read.** The bytes are re-hashed and compared with the digest on
    the version row before a single pixel is drawn. A document altered on disk is
    refused with `integrity_mismatch` rather than displayed as though it were evidence.

    **Watermarked with the viewer**, and **every view is an audit row**
    (`document_viewed`). Access to originals in an evidence system is itself evidence.
    """
    import fitz  # PyMuPDF. Imported here so the module loads without it for unit tests.

    from infra.blobstore import sha256_bytes

    now = datetime.now(timezone.utc)
    async with request.app.state.engine.connect() as conn:
        _, case_id, _ = await _resolve_version(conn, policy, subject, version_id, now)
        sha256 = (
            await conn.execute(
                sa.text("SELECT sha256 FROM document_version WHERE id = :v"), {"v": version_id}
            )
        ).scalar_one()
        viewer = (
            await conn.execute(
                sa.text(
                    "SELECT u.display_name || ' (' || p.title || ')' FROM app_user u "
                    "JOIN post p ON p.id = u.post_id WHERE u.id = :u"
                ),
                {"u": subject.user_id},
            )
        ).scalar_one()

        try:
            data = _read_blob(request.app.state.blobs, sha256)
        except IntegrityMismatch:
            await conn.commit()
            raise HTTPException(status_code=409, detail="integrity_mismatch") from None
        if data is None:
            await conn.commit()
            raise HTTPException(status_code=409, detail="bytes_unavailable")
        if sha256_bytes(data) != sha256:
            await conn.commit()
            raise HTTPException(status_code=409, detail="integrity_mismatch")

        with fitz.open(stream=data, filetype="pdf") as doc:
            if page < 0 or page >= doc.page_count:
                await conn.commit()
                raise NOT_FOUND

        await append_audit(
            conn,
            case_id=case_id,
            actor_id=subject.user_id,
            action=AuditAction.DOCUMENT_VIEWED,
            object_type="document_version",
            object_id=version_id,
            at=now,
        )
        await conn.commit()

    stamp = now.strftime("%Y-%m-%d %H:%M UTC")
    with fitz.open(stream=data, filetype="pdf") as doc:
        target = doc[page]
        _watermark(target, viewer=viewer, stamp=stamp)
        pixmap = target.get_pixmap(matrix=fitz.Matrix(PAGE_ZOOM, PAGE_ZOOM))
        png = pixmap.tobytes("png")

    return Response(
        content=png,
        media_type="image/png",
        # No caching: authorization is re-checked per request, and a cached page in a
        # shared browser outlives the session that was permitted to see it.
        headers={"Cache-Control": "no-store, private"},
    )


@router.get("/versions/{version_id}/integrity")
async def version_integrity(
    version_id: str,
    request: Request,
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
):
    """The five-state verdict for one version, computed now (invariant 5).

    Assembles `VersionFacts` from the version row, the anchor, the disposition record
    and a fresh hash of the bytes on disk, and hands them to the pure `verify_version`.
    Never a boolean: a lawfully disposed document is not a tampered one, and a document
    waiting for its anchor is not a missing one.
    """
    from domain.integrity import AnchorFacts, VersionFacts, verify_version

    now = datetime.now(timezone.utc)
    async with request.app.state.engine.connect() as conn:
        await _resolve_version(conn, policy, subject, version_id, now)
        await conn.commit()
        row = (
            await conn.execute(
                sa.text(
                    "SELECT dv.sha256, dv.lifecycle_state, a.content_sha256 AS anchored, "
                    "       a.seq, a.utc_ts AS anchored_at, "
                    "       EXISTS (SELECT 1 FROM disposition x WHERE x.version_id = dv.id) "
                    "         AS disposed "
                    "FROM document_version dv "
                    "LEFT JOIN anchor_record a ON a.version_id = dv.id WHERE dv.id = :v"
                ),
                {"v": version_id},
            )
        ).mappings().one()

    verdict = verify_version(VersionFacts(
        version_id=version_id,
        lifecycle_state=row["lifecycle_state"],
        recorded_sha256=row["sha256"],
        anchor=AnchorFacts(row["anchored"]) if row["anchored"] else None,
        live_sha256=request.app.state.blobs.digest_of_stored(row["sha256"]),
        disposition_recorded=bool(row["disposed"]),
    ))
    return {
        "state": verdict.state.value,
        "detail": verdict.detail,
        "sha256": row["sha256"],
        "anchor_seq": row["seq"],
        "anchored_at": row["anchored_at"],
        "checked_at": now,
        "anchor_store": "LocalAnchorStore",
        "note": "Hash-chained in the same database; not an independent attestation (AR-4).",
    }


@router.get("/documents/{document_id}/activity")
async def document_activity(
    document_id: str,
    request: Request,
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
):
    """Who did what to this document, from the hash-chained audit trail.

    Restricted to ORIGINAL disclosure. A purpose-limited grantee learning that an
    original's fields were verified, and by whom, is metadata about a document they may
    not read — the same shape of leak as VIC-01, one level out.
    """
    now = datetime.now(timezone.utc)
    try:
        uuid.UUID(document_id)
    except ValueError:
        raise NOT_FOUND
    async with request.app.state.engine.connect() as conn:
        case_id = (
            await conn.execute(
                sa.text("SELECT case_id FROM document WHERE id = :d"), {"d": document_id}
            )
        ).scalar_one_or_none()
        if case_id is None:
            raise NOT_FOUND
        disclosure = await _case_disclosure(conn, policy, subject, case_id, now)
        await conn.commit()
        if disclosure is not Disclosure.ORIGINAL:
            return []
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT a.seq, a.action, a.object_type, a.utc_ts, "
                    "       u.display_name AS actor, p.title AS post "
                    "FROM audit_event a "
                    "LEFT JOIN app_user u ON u.id::text = a.actor_id "
                    "LEFT JOIN post p ON p.id = u.post_id "
                    "WHERE a.object_id IN ("
                    "  SELECT id::text FROM document_version WHERE document_id = :d "
                    "  UNION SELECT f.id::text FROM extracted_field f "
                    "  JOIN document_version v ON v.id = f.version_id "
                    "  WHERE v.document_id = :d"
                    ") ORDER BY a.seq DESC LIMIT 60"
                ),
                {"d": document_id},
            )
        ).mappings().all()
    return [
        {"seq": r["seq"], "action": r["action"], "object_type": r["object_type"],
         "at": r["utc_ts"], "actor": r["actor"], "post": r["post"]}
        for r in rows
    ]


@router.get("/versions/{version_id}/redaction-plan")
async def redaction_plan(
    version_id: str,
    request: Request,
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
):
    """A preview of everything the redaction would remove, before anything is burned.

    The operator sees every region — labelled, propagated into the narrative, matched
    despite an OCR misread, or caught by a pattern — and then decides. Requires
    ORIGINAL: the preview is drawn over the original page.
    """
    import fitz

    from infra.redaction_service import plan_redaction

    now = datetime.now(timezone.utc)
    async with request.app.state.engine.connect() as conn:
        _, case_id, disclosure = await _resolve_version(conn, policy, subject, version_id, now)
        await conn.commit()
        _require_original(disclosure)
        plan, _ = await plan_redaction(conn, version_id=version_id, case_id=case_id)
        # Which findings sit on a labelled field's own span. Everything else is what a
        # field-only redaction would have left readable — the number worth showing.
        labelled_spans = (
            await conn.execute(
                sa.text(
                    "SELECT source_span_start, source_span_end FROM extracted_field "
                    "WHERE version_id = :v AND source_span_start IS NOT NULL"
                ),
                {"v": version_id},
            )
        ).all()
        sha256 = (
            await conn.execute(
                sa.text("SELECT sha256 FROM document_version WHERE id = :v"), {"v": version_id}
            )
        ).scalar_one()
    try:
        data = _read_blob(request.app.state.blobs, sha256)
    except IntegrityMismatch:
        # Geometry for a tampered document is not a smaller answer, it is the wrong
        # question. Refuse it the same way the render does.
        raise HTTPException(status_code=409, detail="integrity_mismatch") from None
    if data is None:
        raise HTTPException(status_code=409, detail="bytes_unavailable")
    width = height = 0.0
    if data is not None:
        with fitz.open(stream=data, filetype="pdf") as doc:
            width, height = doc[0].rect.width, doc[0].rect.height
    return {
        "page_width": width,
        "page_height": height,
        "unlocated": plan.unlocated,
        "findings": [
            {
                "kind": f.kind, "rule_id": f.rule_id, "confidence": f.confidence,
                "source": f.source,
                "labelled": any(s < f.end and e > f.start for s, e in labelled_spans),
                "boxes": [{"page_no": b[0], "x0": b[1], "y0": b[2], "x1": b[3], "y1": b[4]}
                          for b in f.boxes],
            }
            for f in plan.findings
        ],
    }


@router.get("/fields/{field_id}/spans")
async def field_spans(
    field_id: str,
    request: Request,
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
) -> SpanOut:
    """Slice 5b+: char offsets to rectangles, via `ocr_word`.

    Coordinates come back in PDF points, the space the words were recorded in, so the
    client scales them against the rendered image rather than this route guessing a
    zoom. A box is a claim about where a value sits on the original page, so this
    requires ORIGINAL disclosure like the page image does.
    """
    import fitz

    now = datetime.now(timezone.utc)
    async with request.app.state.engine.connect() as conn:
        row, disclosure = await _resolve_field(conn, policy, subject, field_id, now)
        await conn.commit()
        _require_original(disclosure)

        start, end = row["source_span_start"], row["source_span_end"]
        if start is None or end is None:
            # A hand-entered value has no span, and that is not an error.
            return SpanOut(page_no=0, page_width=0, page_height=0, boxes=[])

        words = (
            await conn.execute(
                sa.text(
                    "SELECT page_no, x0, y0, x1, y1 FROM ocr_word "
                    "WHERE version_id = :v AND char_end > :s AND char_start < :e "
                    "ORDER BY page_no, char_start"
                ),
                {"v": str(row["version_id"]), "s": start, "e": end},
            )
        ).mappings().all()

        sha256 = (
            await conn.execute(
                sa.text("SELECT sha256 FROM document_version WHERE id = :v"),
                {"v": str(row["version_id"])},
            )
        ).scalar_one()

    try:
        data = _read_blob(request.app.state.blobs, sha256)
    except IntegrityMismatch:
        raise HTTPException(status_code=409, detail="integrity_mismatch") from None
    if data is None:
        raise HTTPException(status_code=409, detail="bytes_unavailable")
    page_no = words[0]["page_no"] if words else 0
    with fitz.open(stream=data, filetype="pdf") as doc:
        rect = doc[page_no].rect

    return SpanOut(
        page_no=page_no,
        page_width=rect.width,
        page_height=rect.height,
        boxes=[
            Box(x0=w["x0"], y0=w["y0"], x1=w["x1"], y1=w["y1"])
            for w in words
            if w["page_no"] == page_no
        ],
    )


# --- intake -------------------------------------------------------------------


# The title a document is filed under. Whatever the uploader called the file is
# untrusted text: it reaches a screen, a log line and a database row, so it is
# stripped of path separators and control characters and truncated here rather than
# anywhere further in.
_SAFE_TITLE = re.compile(r"[^A-Za-z0-9 ._()\-]")


def _clean_filename(raw: str | None) -> str:
    candidate = (raw or "").strip().replace("\\", "/").split("/")[-1]
    candidate = _SAFE_TITLE.sub("", candidate)[:120].strip()
    return candidate or "untitled.pdf"


@router.post("/cases/{case_id}/documents", status_code=202)
async def upload_document(
    case_id: str,
    request: Request,
    filename: str | None = None,
    # What kind of document this is, for the completeness engine. Validated against the
    # same list as the database check constraint: an unrecognised class would be
    # rejected by the constraint anyway, and a 422 here is a better answer than a 500.
    doc_class: str = "other",
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
):
    """Slice 4b's visible half: upload a PDF, get a sanitised version.

    **The body is the PDF itself**, not a multipart form. FastAPI's `UploadFile` needs
    `python-multipart`, and CLAUDE.md is explicit that a dependency is asked for rather
    than added — so the web tier parses the browser's form with the platform's own
    `FormData` and forwards the bytes here. One fewer package, and this route is
    simpler for it.

    **It validates and versions, and then stops.** The four stages are the worker's
    job. `docker/python.Dockerfile` states the reason: the api image deliberately has
    no Tesseract, because an api that could run OCR invites somebody to call it
    synchronously on a request — which is exactly what an earlier draft of this route
    did. 202, not 201: the version exists, the thread has not run yet.

    Uploading requires disclosure ORIGINAL. A purpose-limited grantee who may read
    derivatives has no business adding evidence to the case (ADR 0014).

    The sanitising happens inside `Pipeline.ingest`, so it cannot be skipped by a
    future caller that does not go through this route.
    """
    from infra.blobstore import LocalBlobStore  # noqa: F401 - type only
    from infra.intake import MAX_BYTES, UploadRejected
    from infra.pipeline import Pipeline

    now = datetime.now(timezone.utc)
    try:
        uuid.UUID(case_id)
    except ValueError:
        raise NOT_FOUND

    # Refuse on the declared length before reading the body, so an oversized upload is
    # never held in memory on an 8 GB machine (threat OPS-03).
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="exceeds_size_limit")

    async with request.app.state.engine.connect() as conn:
        disclosure = await _case_disclosure(conn, policy, subject, case_id, now)
        await conn.commit()
    _require_original(disclosure)

    data = await request.body()
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="exceeds_size_limit")

    # No text source and no signer: `ingest` runs no stage, so it needs neither. An
    # api holding an OCR engine is the thing this split exists to avoid.
    pipeline = Pipeline(blobs=request.app.state.blobs, text_source=None, signer=None)

    async with request.app.state.engine.connect() as conn:
        try:
            if doc_class not in DOC_CLASSES:
                raise HTTPException(status_code=422, detail="unknown_doc_class")
            document_id, version_id, sha256, _source = await pipeline.ingest(
                conn,
                case_id=case_id,
                filename=_clean_filename(filename),
                data=data,
                doc_class=doc_class,
            )
        except UploadRejected as rejected:
            await conn.rollback()
            # The enumerated code, never the parser's message.
            raise HTTPException(status_code=422, detail=rejected.code.value)

        await append_audit(
            conn,
            case_id=case_id,
            actor_id=subject.user_id,
            action=AuditAction.DOCUMENT_UPLOADED,
            object_type="document_version",
            object_id=version_id,
            at=now,
        )
        await conn.commit()

    return {
        "document_id": document_id,
        "version_id": version_id,
        "sha256": sha256,
        "status": "queued",
        "note": "OCR, extraction, signing and anchoring run in the worker.",
    }


class RedactRequest(BaseModel):
    # Empty means every identifying field on the version.
    field_ids: list[str] = Field(default_factory=list, max_length=64)
    include_parties: bool = True
    include_patterns: bool = True


@router.post("/versions/{version_id}/redact", status_code=201)
async def redact_version(
    version_id: str,
    body: RedactRequest,
    request: Request,
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
):
    """Produce a redacted derivative from the named fields. Slice 7, reachable.

    Requires disclosure ORIGINAL for the obvious reason: you cannot redact a document
    you are not permitted to read, and a grantee holding a derivative must not be able
    to make further derivatives of a parent they cannot see.

    A refusal to locate anything is a **422, not a silent success**. Returning a
    "redacted" copy identical to the original would be handed onward as though a name
    had been removed from it.
    """
    from infra.redaction_service import RedactionUnavailable, create_redacted_version

    now = datetime.now(timezone.utc)
    async with request.app.state.engine.connect() as conn:
        _, case_id, disclosure = await _resolve_version(conn, policy, subject, version_id, now)
        _require_original(disclosure)

        try:
            result = await create_redacted_version(
                conn,
                request.app.state.blobs,
                parent_version_id=version_id,
                case_id=case_id,
                field_ids=body.field_ids,
                actor_id=subject.user_id,
                at=now,
                include_parties=body.include_parties,
                include_patterns=body.include_patterns,
            )
        except RedactionUnavailable:
            await conn.rollback()
            raise HTTPException(status_code=422, detail="nothing_located_to_remove")
        await conn.commit()
    return result


# --- the human commit ---------------------------------------------------------


@router.post("/fields/{field_id}/verify")
async def verify_field(
    field_id: str,
    request: Request,
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
) -> FieldOut:
    """Invariant 9's moment: a person takes responsibility for a machine's value.

    The UPDATE is guarded by `status = 'draft'` so a second call is not a second
    attestation — the first author keeps the row. `ck_verified_names_a_human` would
    refuse the write anyway if `verified_by` were ever left null; belt and braces,
    because this is the one write in the build that a court would care about.
    """
    now = datetime.now(timezone.utc)
    async with request.app.state.engine.connect() as conn:
        row, disclosure = await _resolve_field(conn, policy, subject, field_id, now)
        _require_original(disclosure)

        updated = (
            await conn.execute(
                sa.text(
                    "UPDATE extracted_field SET status = 'verified', verified_by = :u, "
                    "       verified_at = :t WHERE id = :f AND status = 'draft' "
                    "RETURNING id"
                ),
                {"u": subject.user_id, "t": now, "f": field_id},
            )
        ).scalar_one_or_none()

        if updated is not None:
            await append_audit(
                conn,
                case_id=str(row["case_id"]),
                actor_id=subject.user_id,
                action=AuditAction.FIELD_VERIFIED,
                object_type="extracted_field",
                object_id=str(field_id),
                at=now,
            )
        await conn.commit()

        fresh = (
            await conn.execute(
                sa.text(
                    "SELECT id, field_key, value, status, source, confidence, "
                    "       source_span_start, source_span_end, provider, model, "
                    "       verified_by, entered_by FROM extracted_field WHERE id = :f"
                ),
                {"f": field_id},
            )
        ).mappings().one()

    return FieldOut(
        id=str(fresh["id"]),
        field_key=fresh["field_key"],
        value=fresh["value"],
        status=fresh["status"],
        source=fresh["source"],
        confidence=fresh["confidence"],
        source_span_start=fresh["source_span_start"],
        source_span_end=fresh["source_span_end"],
        provider=fresh["provider"],
        model=fresh["model"],
        verified_by=str(fresh["verified_by"]) if fresh["verified_by"] else None,
        entered_by=str(fresh["entered_by"]) if fresh["entered_by"] else None,
    )


@router.post("/versions/{version_id}/fields", status_code=201)
async def enter_field(
    version_id: str,
    body: FieldEntry,
    request: Request,
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
) -> FieldOut:
    """A human value: a correction, or manual entry where OCR produced nothing.

    It is a **new row** with `source='human'`, never an UPDATE of the machine's row.
    The extracted value is the record of what the extractor produced, and overwriting
    it destroys the only evidence that the extractor needs fixing.

    Superseding an earlier human value for the same key does overwrite it, and
    authorship follows the latest writer. Version history for hand-entered values is
    not modelled in this build — the chain records that each entry happened and who
    made it, not what the previous text was (ADR 0014, accepted limitation).
    """
    now = datetime.now(timezone.utc)
    async with request.app.state.engine.connect() as conn:
        _, case_id, disclosure = await _resolve_version(conn, policy, subject, version_id, now)
        _require_original(disclosure)

        field_id = (
            await conn.execute(
                sa.text(
                    "INSERT INTO extracted_field "
                    "(id, version_id, case_id, field_key, value, source, status, "
                    " entered_by, entered_at, verified_by, verified_at) "
                    "VALUES (:i, :v, :c, :k, :val, 'human', 'verified', :u, :t, :u, :t) "
                    "ON CONFLICT (version_id, field_key, source) DO UPDATE SET "
                    "  value = EXCLUDED.value, entered_by = EXCLUDED.entered_by, "
                    "  entered_at = EXCLUDED.entered_at, "
                    "  verified_by = EXCLUDED.verified_by, "
                    "  verified_at = EXCLUDED.verified_at "
                    "RETURNING id"
                ),
                {
                    "i": uuid.uuid4(),
                    "v": version_id,
                    "c": case_id,
                    "k": body.field_key,
                    "val": body.value,
                    "u": subject.user_id,
                    "t": now,
                },
            )
        ).scalar_one()

        await append_audit(
            conn,
            case_id=case_id,
            actor_id=subject.user_id,
            action=AuditAction.FIELD_ENTERED,
            object_type="extracted_field",
            object_id=str(field_id),
            at=now,
        )
        await conn.commit()

        fresh = (
            await conn.execute(
                sa.text(
                    "SELECT id, field_key, value, status, source, confidence, "
                    "       source_span_start, source_span_end, provider, model, "
                    "       verified_by, entered_by FROM extracted_field WHERE id = :f"
                ),
                {"f": field_id},
            )
        ).mappings().one()

    return FieldOut(
        id=str(fresh["id"]),
        field_key=fresh["field_key"],
        value=fresh["value"],
        status=fresh["status"],
        source=fresh["source"],
        confidence=fresh["confidence"],
        source_span_start=fresh["source_span_start"],
        source_span_end=fresh["source_span_end"],
        provider=fresh["provider"],
        model=fresh["model"],
        verified_by=str(fresh["verified_by"]) if fresh["verified_by"] else None,
        entered_by=str(fresh["entered_by"]) if fresh["entered_by"] else None,
    )



# --- disposal ---------------------------------------------------------------------

# Enumerated in migration 0005 as a CHECK constraint, and repeated here so a bad value
# is a 422 at the edge rather than an IntegrityError from the driver.
DISPOSAL_BASES = (
    "retention_expiry", "court_order", "erroneous_upload", "superseded_original",
)


class DisposeRequest(BaseModel):
    basis: str = Field(description="One of " + ", ".join(DISPOSAL_BASES))

    @field_validator("basis")
    @classmethod
    def _known_basis(cls, value: str) -> str:
        if value not in DISPOSAL_BASES:
            raise ValueError(f"basis must be one of {DISPOSAL_BASES}")
        return value


@router.post("/versions/{version_id}/dispose", status_code=200)
async def dispose_version(
    version_id: str,
    body: DisposeRequest,
    request: Request,
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
):
    """Lawfully destroy a version's bytes, keeping the anchor and the record of why.

    This is the writer `DISPOSAL_RECORDED` never had, and the reason
    `DISPOSED_ANCHOR_ONLY` was a state nothing in the running system could reach. An
    integrity model with an unreachable state is a model with an untested branch in
    the one place that matters.

    **Anchored first, or not at all.** A version with no anchor cannot be disposed
    (409 `not_anchored`). Destroying bytes you were never able to attest to leaves
    `verify()` returning UNAVAILABLE for ever - an absence nobody can explain - and
    "we destroyed it lawfully" is a claim that needs the anchor to be worth anything.

    **The derived text goes with it.** Threat AR-13 says disposal does not reach
    derived text, and a disposal that left the OCR of a destroyed document sitting in
    `ocr_text` - searchable - would be a disposal in name only. The words, the word
    boxes and the extracted fields are deleted in the same transaction.

    **The bytes go only if nothing else needs them.** The store is content-addressed,
    so one file can back several versions. The address is deleted only when no
    surviving version references it; otherwise the row is disposed and the file stays,
    which is correct and is why `verify()` checks disposal *before* the bytes.

    The honest claim is bounded: **the stored original is destroyed.** Write-ahead
    logs, snapshots and any backup taken before now are out of reach of this code, and
    saying "the document is destroyed" would be a claim this build cannot support
    (AR-13). Disposal is also unilateral - two-person approval was cut (AR-15) - so it
    rests on attribution, which is why the audit row is written in the same
    transaction as the deletion.
    """
    now = datetime.now(timezone.utc)
    engine = request.app.state.engine
    blobs = request.app.state.blobs

    async with engine.begin() as conn:
        _, case_id, disclosure = await _resolve_version(
            conn, policy, subject, version_id, now
        )
        # Destroying a document you are only permitted to see redacted is not a thing
        # to allow, for the same reason attesting to one is not (ADR 0014).
        _require_original(disclosure)

        row = (
            await conn.execute(
                sa.text(
                    "SELECT dv.sha256, dv.lifecycle_state, "
                    "       a.content_sha256 IS NOT NULL AS anchored, "
                    "       EXISTS (SELECT 1 FROM disposition x WHERE x.version_id = dv.id) "
                    "         AS already "
                    "FROM document_version dv "
                    "LEFT JOIN anchor_record a ON a.version_id = dv.id "
                    "WHERE dv.id = :v"
                ),
                {"v": version_id},
            )
        ).mappings().one()

        if row["already"] or row["lifecycle_state"] == "disposed":
            # Idempotent in effect but reported honestly: a second disposal is not a
            # second lawful act, and silently succeeding would put a second row on
            # the chain for something that did not happen.
            raise HTTPException(status_code=409, detail="already_disposed")
        if not row["anchored"]:
            raise HTTPException(status_code=409, detail="not_anchored")

        sha256 = row["sha256"]
        await conn.execute(
            sa.text(
                "UPDATE document_version SET lifecycle_state = 'disposed' WHERE id = :v"
            ),
            {"v": version_id},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO disposition (id, version_id, disposed_at, disposed_by, basis) "
                "VALUES (:i, :v, :t, :u, :b)"
            ),
            {"i": str(uuid.uuid4()), "v": version_id, "t": now,
             "u": subject.user_id, "b": body.basis},
        )
        # AR-13's first half. The search index is a functional GIN over ocr_text
        # (migration 0010), so deleting the row removes the document from search too.
        for statement in (
            "DELETE FROM extracted_field WHERE version_id = :v",
            "DELETE FROM ocr_word WHERE version_id = :v",
            "DELETE FROM ocr_text WHERE version_id = :v",
        ):
            await conn.execute(sa.text(statement), {"v": version_id})

        # Is any surviving version still backed by this address?
        shared = (
            await conn.execute(
                sa.text(
                    "SELECT count(*) FROM document_version "
                    "WHERE sha256 = :h AND id <> :v AND lifecycle_state <> 'disposed'"
                ),
                {"h": sha256, "v": version_id},
            )
        ).scalar_one()

        await append_audit(
            conn,
            case_id=case_id,
            actor_id=subject.user_id,
            action=AuditAction.DISPOSAL_RECORDED,
            object_type="version",
            object_id=version_id,
            at=now,
        )

    # Outside the transaction, deliberately. A filesystem unlink cannot be rolled
    # back, so it happens only after the record of it has committed: a disposal
    # recorded with the bytes still present is recoverable, and bytes destroyed with
    # no record is the failure this ordering exists to avoid.
    bytes_destroyed = False
    if not shared:
        bytes_destroyed = blobs.delete(sha256)

    log.info(
        "version disposed",
        extra={"version_id": version_id, "case_id": case_id, "basis": body.basis,
               "bytes_destroyed": bytes_destroyed},
    )
    return {
        "version_id": version_id,
        "lifecycle_state": "disposed",
        "basis": body.basis,
        "bytes_destroyed": bytes_destroyed,
        "shared_address_retained": bool(shared),
        # Two sentences, chosen by what actually happened. Returning the first
        # unconditionally said "the stored original is destroyed" on the exact path
        # where this route had deliberately KEPT the bytes because another version
        # still relied on them - the system claiming an erasure it had just decided
        # not to perform. The caller repeats whatever it is told, so being right here
        # is what stops a false destruction notice reaching a screen.
        "note": (
            (
                "The derived text is removed and this version is disposed, but the "
                "stored bytes were RETAINED: another version of this case is backed by "
                "the same content address, and destroying them would have destroyed it "
                "too. This version verifies as DISPOSED_ANCHOR_ONLY."
            )
            if shared
            else (
                "The stored original is destroyed and its derived text removed. "
                "Backups, snapshots and write-ahead logs taken before now are out of "
                "reach of this system (AR-13). The anchor and this disposition record "
                "survive, so the version verifies as DISPOSED_ANCHOR_ONLY."
            )
        ),
    }
