"""The worker's half of the golden thread: process versions nobody has processed.

**Why this exists rather than the api doing it.** `docker/python.Dockerfile` says
plainly that the api target has no Tesseract, because an api that could run OCR invites
somebody to call it synchronously on a request. Slice 4b's upload route very nearly
became that. Instead the route validates, sanitises and creates the version — which
needs no OCR engine — and stops. This picks it up.

That also matches what CLAUDE.md decided about the queue: a Postgres table with
`FOR UPDATE SKIP LOCKED`, no Redis, fewer moving parts and one less thing to explain at
3am. The claim below is exactly that, over `document_version` rows that have no
`ocr_text` yet.

**The worker sits outside the authorization model**, deliberately and unavoidably: to
OCR anything it must read every original (threat CD-01). It connects as `ordin_app`,
owns nothing, and nothing it writes carries document content into a field read back
over the API.

Nothing here re-sanitises. Sanitising is deterministic but not its own fixed point
(ADR 0017), so re-running it on stored bytes could mint a second version of a document
this was only asked to process.
"""
import logging

import sqlalchemy as sa

from domain.enums import JobStage
from infra.pipeline import MAX_STAGE_ATTEMPTS

log = logging.getLogger("ordin.worker.intake")

# The stages a version owes, in the order `Pipeline.process_version` runs them. Derived
# from the enum rather than typed out, so a stage added there cannot be silently left
# out of the readiness question - which would make its failure invisible to the queue.
STAGES = [
    JobStage.OCR.value, JobStage.EXTRACT.value, JobStage.SIGN.value, JobStage.ANCHOR.value,
]

# One version per tick. The worker's tick is ten seconds, and a demo machine running
# Tesseract on a page for a couple of seconds should not be holding a transaction open
# across a batch.
BATCH = 1


async def claim_unprocessed(conn) -> list[dict]:
    """Versions that still owe a stage, locked so a second worker takes different rows.

    `SKIP LOCKED` is what makes a second worker useful rather than a duplicate: it
    takes the next row instead of waiting for this one. The stage-level idempotency
    key would catch a double-claim anyway — this just avoids the wasted work.

    **The readiness question is about JOBS, not about `ocr_text`.** This used to be
    `LEFT JOIN ocr_text WHERE o.id IS NULL`, and that single predicate caused both of
    the queue's failures:

    *A failed anchor was never retried.* Once OCR succeeded the `ocr_text` row existed,
    so the version left the ready set permanently — whether or not extract, sign or
    anchor had ever run. `process_version` breaks out of the stage loop on the first
    failure, so a brief anchor outage left documents with OCR and draft fields and no
    anchor, `verify()` reporting PENDING for ever, and no way out: `dispose_version`
    refuses an unanchored version with 409 `not_anchored`. CLAUDE.md promises
    "anchoring is a separate retryable stage". It was separate. It was not retryable.

    *A permanently failing document starved everything.* The reverse case: a version
    whose OCR always raised never got an `ocr_text` row, so it always satisfied the
    predicate, and being ordered oldest-first with one row per tick it occupied the
    only slot for ever. Every later upload queued behind it and was never processed.

    Asking "is any stage neither succeeded nor exhausted?" answers both. A stage that
    has run out of attempts stops making its version ready; a stage that failed with
    attempts to spare keeps it ready. `MAX_STAGE_ATTEMPTS` lives in `infra/pipeline.py`
    and is imported rather than repeated, because two copies of a retry cap is how the
    queue and the claim end up disagreeing about what is finished.
    """
    rows = (
        await conn.execute(
            sa.text(
                "SELECT dv.id AS version_id, dv.document_id, dv.sha256, "
                "       dv.source_sha256, d.case_id "
                "FROM document_version dv "
                "JOIN document d ON d.id = dv.document_id "
                "WHERE dv.derived_from_version_id IS NULL "
                "  AND dv.lifecycle_state = 'active' "
                # work is still owed: some stage has no successful job
                "  AND EXISTS ( "
                "        SELECT 1 FROM unnest(:stages ::text[]) AS s(stage) "
                "        WHERE NOT EXISTS ( "
                "                SELECT 1 FROM processing_job j "
                "                WHERE j.document_version_id = dv.id "
                "                  AND j.stage = s.stage AND j.status = 'succeeded')) "
                # and nothing has been given up on. ANY exhausted stage retires the
                # version, because `process_version` runs the stages in order and stops
                # at the first failure - so once one is out of attempts the later ones
                # can never run, and leaving them 'owed' put the version back in the
                # ready set on every tick. That was the starvation, surviving the fix.
                "  AND NOT EXISTS ( "
                "        SELECT 1 FROM processing_job j "
                "        WHERE j.document_version_id = dv.id AND j.attempts >= :cap) "
                "ORDER BY dv.created_at "
                "LIMIT :n FOR UPDATE OF dv SKIP LOCKED"
            ),
            {"n": BATCH, "cap": MAX_STAGE_ATTEMPTS, "stages": STAGES},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def process_pending(conn, pipeline, *, actor_id: str) -> int:
    """Process one batch. Returns how many versions were attempted.

    A derivative is excluded on purpose: whether a redacted version should itself be
    OCR'd and indexed is an open question in STATUS, not something to settle by
    omission in a queue query. It is written here so the omission is visible.
    """
    claimed = await claim_unprocessed(conn)
    for row in claimed:
        result = await pipeline.process_version(
            conn,
            case_id=str(row["case_id"]),
            document_id=str(row["document_id"]),
            version_id=str(row["version_id"]),
            content_sha256=row["sha256"],
            source_sha256=row["source_sha256"] or row["sha256"],
            actor_id=actor_id,
        )
        failed = [s.stage for s in result.stages if s.error_code]
        # Ids and enumerated codes only (invariant 12). No filename, no content.
        log.info(
            "version processed",
            extra={
                "version_id": str(row["version_id"]),
                "stages": len(result.stages),
                "failed_stages": failed,
            },
        )
    return len(claimed)
