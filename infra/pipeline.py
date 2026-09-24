"""The golden thread, headless.

    upload -> validate -> version -> OCR -> extract -> sign -> hash -> anchor

Every stage is a `ProcessingJob` carrying the idempotency key from docs/adr/0004:

    key = SHA256(case_id || content_sha256 || operation || params_hash)

**The acceptance criterion is that running this twice on one upload yields exactly
one version, one extraction run, one field set, one anchor.** That is a property of
the database, not of this file: a UNIQUE constraint enforces it where a code path
merely intends it. The job's `idempotency_key` is UNIQUE, `ocr_text.version_id` is
UNIQUE, `extracted_field` is UNIQUE per (version, key, source), and
`anchor_record.version_id` is UNIQUE. This module's job is to *notice* the conflict
and skip rather than to be the thing preventing duplication.

Why the key is scoped to the case (ADR 0004): keyed on content alone, uploading a
document you already hold into your own sandbox case would report "already exists"
for a copy held in a case you cannot read - a cross-case existence oracle (threat
INS-06). `params_hash` covers stage parameters so a corrected redaction manifest
produces a new key rather than returning the flawed derivative.

Invariant 9 holds throughout: nothing here writes `status='verified'`. Extraction
produces drafts. The database refuses anything else (ck_verified_names_a_human).
"""
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import sqlalchemy as sa

from domain.enums import JobStage, JobStatus
from domain.extraction import extract_fields, extract_statutory_references
from infra.anchor import LocalAnchorStore
from infra.blobstore import BlobStore, sha256_bytes
from infra.esign import SimulatedESignProvider
from infra.intake import sanitise
from infra.textsource import TextSource, TextSourceUnavailable


def idempotency_key(
    *, case_id: str, content_sha256: str, operation: str, params: dict | None = None
) -> str:
    """docs/adr/0004. Case-scoped, so it cannot answer questions across a boundary."""
    params_hash = hashlib.sha256(
        json.dumps(params or {}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    material = f"{case_id}|{content_sha256}|{operation}|{params_hash}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass
class StageOutcome:
    stage: str
    status: str
    skipped: bool = False
    output_ref: str | None = None
    error_code: str | None = None


@dataclass
class PipelineResult:
    document_id: str
    version_id: str
    content_sha256: str
    stages: list[StageOutcome] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(s.status != JobStatus.FAILED for s in self.stages)


class Pipeline:
    def __init__(
        self,
        blobs: BlobStore,
        text_source: TextSource,
        signer: SimulatedESignProvider,
        anchors: LocalAnchorStore | None = None,
    ) -> None:
        self.blobs = blobs
        self.text_source = text_source
        self.signer = signer
        self.anchors = anchors or LocalAnchorStore()

    # --- job bookkeeping ------------------------------------------------------

    async def _claim(self, conn, *, version_id, stage: str, key: str) -> tuple[bool, str | None]:
        """Claim a stage, or report that it already ran.

        ON CONFLICT DO NOTHING on the unique key is what makes a concurrent second
        worker lose the race cleanly instead of duplicating the work. Returns
        (claimed, existing_output_ref).
        """
        inserted = (
            await conn.execute(
                sa.text(
                    "INSERT INTO processing_job "
                    "(id, document_version_id, stage, status, idempotency_key, attempts, started_at) "
                    "VALUES (:id, :v, :stage, 'running', :key, 1, now()) "
                    "ON CONFLICT (idempotency_key) DO NOTHING RETURNING id"
                ),
                {"id": uuid.uuid4(), "v": version_id, "stage": stage, "key": key},
            )
        ).scalar_one_or_none()
        if inserted is not None:
            return True, None

        existing = (
            await conn.execute(
                sa.text(
                    "SELECT status, output_ref FROM processing_job WHERE idempotency_key = :key"
                ),
                {"key": key},
            )
        ).mappings().one()
        if existing["status"] == JobStatus.SUCCEEDED:
            return False, existing["output_ref"]
        # A previous attempt failed or died mid-flight. Retry it, counting the attempt
        # - "retry count" is one of the things the reliability invariant requires.
        await conn.execute(
            sa.text(
                "UPDATE processing_job SET status='running', attempts = attempts + 1, "
                "started_at = now(), error_code = NULL WHERE idempotency_key = :key"
            ),
            {"key": key},
        )
        return True, None

    async def _finish(self, conn, key: str, *, status: str, output_ref: str | None = None,
                      error_code: str | None = None, provider: str | None = None,
                      maturity: str | None = None) -> None:
        await conn.execute(
            sa.text(
                "UPDATE processing_job SET status=:s, finished_at=now(), "
                "output_ref=:o, error_code=:e, provider=:p, maturity=:m "
                "WHERE idempotency_key = :key"
            ),
            {"s": status, "o": output_ref, "e": error_code, "p": provider,
             "m": maturity, "key": key},
        )

    # --- the thread -----------------------------------------------------------

    async def ingest(
        self,
        conn,
        *,
        case_id: str,
        filename: str,
        data: bytes,
        doc_class: str = "other",
    ) -> tuple[str, str, str, str]:
        """Validate and version, without running a single stage.

        Split out from `run` so the api can accept an upload **without needing an OCR
        engine**. `docker/python.Dockerfile` states the reason plainly: the api target
        deliberately has no Tesseract, because an api that could run OCR invites
        somebody to call it synchronously on a request. Honouring that means the
        upload route ends here and the worker picks the version up.

        Returns (document_id, version_id, content_sha256, source_sha256).
        """
        # Slice 4b: validate before version. The thread is upload -> validate ->
        # version, and this is the validate. Sanitising here rather than at the HTTP
        # boundary means **no caller can create a version from unsanitised bytes** -
        # not a route added later, not a fixture loader, not a test. `sanitise` raises
        # `UploadRejected` with an enumerated code; nothing is written when it does.
        #
        # What is stored, hashed, signed and anchored is the sanitised file. Anchoring
        # the digest of the upload would anchor something the system does not hold.
        intake = sanitise(data)

        # **Identity is the digest of what arrived, not of what is stored** (ADR 0017,
        # migration 0008). Keying on the stored digest made the identity of an upload
        # depend on the sanitiser being byte-stable for the life of the process, and
        # PyMuPDF very nearly is: its output occasionally differs by a few bytes as
        # mupdf compacts object numbering. The symptom was the idempotency tests
        # failing intermittently in full runs and passing alone, in a different test
        # each time.
        document_id, version_id = await self._upsert_version(
            conn, case_id=case_id, filename=filename, data=intake.data,
            content_sha256=intake.sha256, source_sha256=intake.original_sha256,
            doc_class=doc_class,
        )
        return (
            str(document_id), str(version_id), intake.sha256, intake.original_sha256,
        )

    async def run(
        self, conn, *, case_id: str, actor_id: str, filename: str, data: bytes,
        at: datetime | None = None, doc_class: str = "other",
    ) -> PipelineResult:
        """Ingest and then process, in one call. The headless path and the tests."""
        at = at or datetime.now(timezone.utc)
        document_id, version_id, content_sha256, source_sha256 = await self.ingest(
            # Passed through rather than defaulted here: `run` and `ingest` must
            # classify identically, or a document filed through the headless path is
            # invisible to the completeness engine while the same file uploaded through
            # the API is counted.
            conn, case_id=case_id, filename=filename, data=data, doc_class=doc_class
        )
        return await self.process_version(
            conn, case_id=case_id, document_id=document_id, version_id=version_id,
            content_sha256=content_sha256, source_sha256=source_sha256,
            actor_id=actor_id, at=at,
        )

    async def process_version(
        self, conn, *, case_id: str, document_id: str, version_id: str,
        content_sha256: str, source_sha256: str, actor_id: str,
        at: datetime | None = None,
    ) -> PipelineResult:
        """Run the four stages against a version that already exists.

        Deliberately does **not** re-sanitise. Sanitising is deterministic but is not
        its own fixed point (ADR 0017), so a worker that re-ran it on stored bytes
        could produce a second version of a document it was only supposed to process.
        """
        at = at or datetime.now(timezone.utc)
        result = PipelineResult(
            document_id=str(document_id), version_id=str(version_id),
            content_sha256=content_sha256,
        )

        for stage, runner in (
            (JobStage.OCR, self._stage_ocr),
            (JobStage.EXTRACT, self._stage_extract),
            (JobStage.SIGN, self._stage_sign),
            (JobStage.ANCHOR, self._stage_anchor),
        ):
            key = idempotency_key(
                case_id=str(case_id), content_sha256=source_sha256, operation=stage.value
            )
            claimed, existing = await self._claim(conn, version_id=version_id, stage=stage.value,
                                                  key=key)
            if not claimed:
                result.stages.append(
                    StageOutcome(stage.value, JobStatus.SUCCEEDED, skipped=True,
                                 output_ref=existing)
                )
                continue
            try:
                output_ref, provider, maturity = await runner(
                    conn, case_id=case_id, document_id=document_id, version_id=version_id,
                    actor_id=actor_id, content_sha256=content_sha256, at=at,
                )
            except TextSourceUnavailable:
                # A missing engine is a failed stage with a code, never a fallback.
                await self._finish(conn, key, status=JobStatus.FAILED,
                                   error_code="text_source_unavailable")
                result.stages.append(
                    StageOutcome(stage.value, JobStatus.FAILED,
                                 error_code="text_source_unavailable")
                )
                break
            except Exception as exc:  # noqa: BLE001
                # Enumerated code only. Persisting the exception text would carry
                # document content back out over the job-status route (threat CD-01).
                await self._finish(conn, key, status=JobStatus.FAILED,
                                   error_code=type(exc).__name__)
                result.stages.append(
                    StageOutcome(stage.value, JobStatus.FAILED, error_code=type(exc).__name__)
                )
                break

            await self._finish(conn, key, status=JobStatus.SUCCEEDED, output_ref=output_ref,
                               provider=provider, maturity=maturity)
            result.stages.append(StageOutcome(stage.value, JobStatus.SUCCEEDED,
                                              output_ref=output_ref))

        return result

    async def _upsert_version(
        self, conn, *, case_id, filename, data, content_sha256, source_sha256=None,
        doc_class="other",
    ):
        """Store the bytes and find-or-create the version.

        Found by the **source** digest — what arrived — falling back to the stored
        digest for rows written before migration 0008. Originals are never overwritten
        (reliability invariant); this either matches what is there or adds a new
        version number.

        **The lookup happens before the bytes are stored, and a disposed version is
        invisible to it.** Both halves of that sentence are load-bearing:

        `put` used to run first, unconditionally. Re-uploading a lawfully disposed
        document therefore wrote its bytes back to the same content address — the
        address is a digest of the plaintext, so it is the same file — and then matched
        the disposed row and returned it. The result was a document whose disposition
        record, `lifecycle_state` and `verify()` all said "lawfully disposed; bytes not
        retained" while the bytes sat in the store. `verify()` checks disposal *before*
        the bytes, correctly and by design (invariant 5), so nothing could ever notice.
        A system that exists to say truthfully what it holds was saying the opposite.

        Excluding disposed rows is the other half. Re-filing a document that was
        disposed in error is legitimate, and versions are append-only, so it becomes a
        **new** version rather than resurrecting the old record. A second re-upload then
        matches that new active version, so idempotency survives.
        """
        existing = (
            await conn.execute(
                sa.text(
                    "SELECT dv.id, dv.document_id FROM document_version dv "
                    "JOIN document d ON d.id = dv.document_id "
                    "WHERE d.case_id = :c "
                    "  AND dv.lifecycle_state <> 'disposed' "
                    "  AND (dv.source_sha256 = :src "
                    "       OR (dv.source_sha256 IS NULL AND dv.sha256 = :h)) "
                    "LIMIT 1"
                ),
                {"c": case_id, "h": content_sha256, "src": source_sha256 or content_sha256},
            )
        ).mappings().one_or_none()
        if existing:
            # Deliberately no `put` here. The bytes for a version that already exists
            # are already stored, or they are gone and `verify()` must say so - and
            # silently restoring them on re-upload would erase the one signal that says
            # a document went missing.
            return existing["document_id"], existing["id"]

        self.blobs.put(data)

        document_id = (
            await conn.execute(
                sa.text("SELECT id FROM document WHERE case_id = :c AND title = :t"),
                {"c": case_id, "t": filename},
            )
        ).scalar_one_or_none()
        if document_id is None:
            document_id = uuid.uuid4()
            await conn.execute(
                sa.text(
                    "INSERT INTO document (id, case_id, title, doc_class) "
                    "VALUES (:i,:c,:t,:k)"
                ),
                {"i": document_id, "c": case_id, "t": filename, "k": doc_class},
            )
        elif doc_class != "other":
            # A later upload of the same filename may classify a document that was
            # filed as `other` first. It never RE-classifies: a document already
            # declared an FIR is not silently turned into something else by whoever
            # uploads next, because that would move a case's completeness without
            # anybody deciding to.
            await conn.execute(
                sa.text(
                    "UPDATE document SET doc_class = :k "
                    "WHERE id = :i AND doc_class = 'other'"
                ),
                {"k": doc_class, "i": document_id},
            )

        next_no = (
            await conn.execute(
                sa.text(
                    "SELECT COALESCE(MAX(version_no), 0) + 1 FROM document_version "
                    "WHERE document_id = :d"
                ),
                {"d": document_id},
            )
        ).scalar_one()
        version_id = uuid.uuid4()
        await conn.execute(
            sa.text(
                "INSERT INTO document_version "
                "(id, document_id, version_no, sha256, source_sha256) "
                "VALUES (:i,:d,:n,:h,:src)"
            ),
            {"i": version_id, "d": document_id, "n": next_no, "h": content_sha256,
             "src": source_sha256 or content_sha256},
        )
        return document_id, version_id

    # --- stages ---------------------------------------------------------------

    async def _stage_ocr(self, conn, *, version_id, content_sha256, **_):
        data = self.blobs.get(content_sha256)
        if data is None:
            raise FileNotFoundError("blob missing")
        outcome = self.text_source.extract(data)

        await conn.execute(
            sa.text(
                "INSERT INTO ocr_text (id, version_id, text, method, provider, model, "
                " maturity, mean_confidence, requires_manual_entry) "
                "VALUES (:i,:v,:t,:me,:p,:mo,:ma,:c,:r) "
                "ON CONFLICT (version_id) DO NOTHING"
            ),
            {"i": uuid.uuid4(), "v": version_id, "t": outcome.text, "me": outcome.method,
             "p": outcome.provider, "mo": outcome.model, "ma": outcome.maturity,
             "c": outcome.mean_confidence, "r": outcome.requires_manual_entry},
        )
        already = (
            await conn.execute(
                sa.text("SELECT count(*) FROM ocr_word WHERE version_id = :v"),
                {"v": version_id},
            )
        ).scalar_one()
        if not already:
            for w in outcome.words:
                await conn.execute(
                    sa.text(
                        "INSERT INTO ocr_word (version_id, page_no, char_start, char_end, "
                        " x0, y0, x1, y1, confidence) "
                        "VALUES (:v,:pg,:cs,:ce,:x0,:y0,:x1,:y1,:cf)"
                    ),
                    {"v": version_id, "pg": w.page_no, "cs": w.char_start, "ce": w.char_end,
                     "x0": w.x0, "y0": w.y0, "x1": w.x1, "y1": w.y1, "cf": w.confidence},
                )
        return f"ocr_text:{version_id}", outcome.provider, outcome.maturity

    async def _stage_extract(self, conn, *, version_id, case_id, **_):
        row = (
            await conn.execute(
                sa.text("SELECT text, requires_manual_entry FROM ocr_text WHERE version_id = :v"),
                {"v": version_id},
            )
        ).mappings().one_or_none()
        if row is None:
            raise LookupError("no ocr text")
        if row["requires_manual_entry"]:
            # Deliberately extracts nothing. Low-confidence OCR routed to a human is
            # not a page to run patterns over and call draft evidence.
            return f"manual_entry_required:{version_id}", "ordin.regex", "mvp"

        count = 0
        # Labelled fields, then statutory references. Both land in the same table, with
        # the same draft status and the same human commit, because a detected citation
        # is exactly as provisional as a detected name: a pattern matched, and nobody
        # has agreed with it yet (invariant 9).
        for found in [*extract_fields(row["text"]), *extract_statutory_references(row["text"])]:
            await conn.execute(
                sa.text(
                    "INSERT INTO extracted_field "
                    "(id, version_id, case_id, field_key, value, source, source_span_start, "
                    " source_span_end, confidence, provider, model, status) "
                    "VALUES (:i,:v,:c,:k,:val,'regex',:s,:e,:cf,'ordin.regex',:m,'draft') "
                    "ON CONFLICT (version_id, field_key, source) DO NOTHING"
                ),
                {"i": uuid.uuid4(), "v": version_id, "c": case_id, "k": found.field_key,
                 "val": found.value, "s": found.span_start, "e": found.span_end,
                 "cf": found.confidence, "m": found.extractor_version},
            )
            count += 1
        return f"extracted_field:{count}", "ordin.regex", "mvp"

    async def _stage_sign(self, conn, *, case_id, document_id, version_id, actor_id,
                          content_sha256, at):
        signature = self.signer.sign(
            case_id=case_id, document_id=document_id, version_id=version_id,
            content_sha256=content_sha256, actor_id=actor_id, at=at,
        )
        return f"signature:{signature.value[:16]}", signature.provider, signature.maturity

    async def _stage_anchor(self, conn, *, case_id, document_id, version_id, actor_id,
                            content_sha256, at):
        """Separately retryable, and an outage here never corrupts case state.

        It is the last stage for that reason: everything before it is already durable,
        so a case whose anchor is pending is valid (and verify() reports PENDING).
        """
        row_hash = await self.anchors.anchor(
            conn, case_id=case_id, document_id=document_id, version_id=version_id,
            content_sha256=content_sha256, actor_id=actor_id, at=at,
        )
        return f"anchor:{row_hash[:16]}", "LocalAnchorStore", "mvp"
