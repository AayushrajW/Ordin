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
import re
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from api.deps import policy as get_policy
from api.deps import require_subject
from domain.enums import AuditAction
from domain.policy import Policy
from domain.subject import Subject
from infra.audit_log import append_audit
from infra.authz import decide, load_case_facts
from infra.decisions import record_decision
from infra.disclosure import (
    Disclosure,
    disclosure_for,
    readable_ocr_text,
    readable_version_ids,
)
from infra.logging_context import current_correlation_id

router = APIRouter(tags=["documents"])

# Rendered at 2x for a legible scan on a laptop screen without shipping a 4 MB PNG.
PAGE_ZOOM = 2.0

NOT_FOUND = HTTPException(status_code=404, detail="not_found")


class DocumentOut(BaseModel):
    id: str
    title: str
    disclosure: str
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


# --- resolution ---------------------------------------------------------------


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
            versions=await _versions(conn, version_ids),
        )


@router.get("/versions/{version_id}/fields")
async def version_fields(
    version_id: str,
    request: Request,
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
) -> list[FieldOut]:
    # `_resolve_version` is the gate, and it is a stronger one than
    # `readable_fields`: that function decides whether a version's field values may be
    # disclosed, while this refuses the version itself unless it is in the subject's
    # readable set. Reaching this select at all means the version is disclosable, so
    # the extra columns the screen needs come back with it rather than through a
    # second, narrower query that would then need widening.
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
    return [
        FieldOut(
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
        )
        for r in rows
    ]


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


@router.get("/versions/{version_id}/page.png")
async def version_page(
    version_id: str,
    request: Request,
    page: int = 0,
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
) -> Response:
    """The scan, rendered server-side.

    Rendered rather than served as a PDF on purpose: a PDF handed to the browser is
    executed by a viewer, and for a derivative it would also ship whatever the
    container still holds. A PNG of the page is the same evidence with none of that.
    """
    import fitz  # PyMuPDF. Imported here so the module loads without it for unit tests.

    now = datetime.now(timezone.utc)
    async with request.app.state.engine.connect() as conn:
        await _resolve_version(conn, policy, subject, version_id, now)
        await conn.commit()
        sha256 = (
            await conn.execute(
                sa.text("SELECT sha256 FROM document_version WHERE id = :v"), {"v": version_id}
            )
        ).scalar_one()

    data = request.app.state.blobs.get(sha256)
    if data is None:
        # The bytes are gone: that is UNAVAILABLE, not a rendering error, and the
        # verify() route is where that distinction is reported.
        raise HTTPException(status_code=409, detail="bytes_unavailable")

    with fitz.open(stream=data, filetype="pdf") as doc:
        if page < 0 or page >= doc.page_count:
            raise NOT_FOUND
        pixmap = doc[page].get_pixmap(matrix=fitz.Matrix(PAGE_ZOOM, PAGE_ZOOM))
        png = pixmap.tobytes("png")

    return Response(
        content=png,
        media_type="image/png",
        # No caching: authorization is re-checked per request, and a cached page in a
        # shared browser outlives the session that was permitted to see it.
        headers={"Cache-Control": "no-store, private"},
    )


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

    data = request.app.state.blobs.get(sha256)
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
            document_id, version_id, sha256, _source = await pipeline.ingest(
                conn, case_id=case_id, filename=_clean_filename(filename), data=data
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
    field_ids: list[str] = Field(min_length=1, max_length=64)


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

