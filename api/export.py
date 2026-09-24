"""Taking a copy: the export verb, and the accounting that makes it countable.

**Why this is a separate route rather than a download link on the viewer.** Threat
AR-17 says bulk export is unmetered, and its stated mitigation is the modest one that
fits this budget: *make export a distinct verb in the audit chain recording row count
and filter - accounting, not prevention.* Before this, reading a document and taking a
copy of it were the same event to the system, so the difference between an officer
working a case and an officer emptying it was invisible. Nothing here stops anybody.
It makes the question answerable.

**The bytes are exported unmodified, and that is a decision.** The page renderer
watermarks with the viewer's name and the time (threat AR-7); this does not. A
watermark would change the bytes, and changed bytes do not hash to the anchored digest
- which destroys the one property that makes an export evidential. A recipient must be
able to run `sha256sum` on what they were handed and have it match what the case record
says. So the copy is byte-exact and the attribution lives in `export_record` and on the
audit chain instead. That trade is worth stating plainly: **this build can prove what
was taken and by whom; it cannot mark the copy itself.** AR-7 is unchanged.

**A document that does not verify is never handed over as evidence.** A single-version
export of a tampered document is refused outright. A case export continues, lists the
version in the manifest with its state, and omits its bytes - counted in
`excluded_count`, because an export that silently dropped a mismatched document would
be the quietest possible way to lose the alert.

**Disclosure decides what is in the bundle.** `readable_version_ids` is the same
function the viewer uses, so a subject holding a purpose-limited grant exports
derivatives and nothing else. There is no second code path here that could disagree
with the first (threat VIC-01).
"""
import io
import json
import uuid
import zipfile
from datetime import datetime, timezone

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from api.deps import policy as get_policy
from api.deps import require_subject
from api.documents import (
    NOT_FOUND,
    IntegrityMismatch,
    _case_disclosure,
    _clean_filename,
    _read_blob,
    _resolve_version,
)
from domain.enums import AuditAction
from domain.integrity import AnchorFacts, VersionFacts, VerificationState, verify_version
from domain.policy import Policy
from domain.subject import Subject
from infra.audit_log import append_audit
from infra.disclosure import Disclosure, readable_version_ids

router = APIRouter(tags=["export"])

# A case export builds the archive in memory, and the api container is capped at
# 256 MiB (docker-compose.yml). These are not policy limits, they are the limits of
# the machine this runs on, and refusing loudly is better than being OOM-killed
# halfway through writing a response - which would look to the caller exactly like
# the export succeeding and the connection dropping.
MAX_EXPORT_DOCUMENTS = 50
# Sized against the actual peak rather than against the number that sounded generous.
# Streaming holds one document (at most MAX_BYTES from infra/intake.py, 25 MB) plus the
# compressed archive plus the copy `getvalue()` makes: 25 + 32 + 32 is about 89 MB
# inside a 256 MiB container, with room for the rest of the process. At 64 MB it was
# about 153 MB, which is not a limit, it is a slower OOM.
MAX_EXPORT_BYTES = 32 * 1024 * 1024


async def _record_export(
    conn,
    *,
    case_id: str,
    subject: Subject,
    scope: str,
    disclosure: Disclosure,
    row_count: int,
    byte_count: int,
    excluded_count: int = 0,
) -> str:
    """One row per export. Enumerated columns and counts, never a description.

    AR-17 asks for "row count and filter". The filter is recorded as the disclosure
    class and the scope rather than as text, because a free-text column here is where
    a case reference or a search term eventually lands (invariant 12).
    """
    record_id = str(uuid.uuid4())
    await conn.execute(
        sa.text(
            "INSERT INTO export_record "
            "(id, case_id, actor_id, scope, disclosure, row_count, byte_count, "
            " excluded_count) "
            "VALUES (:i, :c, :a, :s, :d, :r, :b, :x)"
        ),
        {
            "i": record_id, "c": case_id, "a": subject.user_id, "s": scope,
            "d": disclosure.value, "r": row_count, "b": byte_count, "x": excluded_count,
        },
    )
    return record_id


async def _verdict(conn, blobs, version_id: str) -> tuple[VerificationState, dict]:
    """The five-state verdict for one version, and the row it was computed from."""
    row = (
        await conn.execute(
            sa.text(
                "SELECT dv.id, dv.document_id, dv.version_no, dv.sha256, "
                "       dv.lifecycle_state, d.title, "
                "       a.content_sha256 AS anchored, "
                "       EXISTS (SELECT 1 FROM disposition x WHERE x.version_id = dv.id) "
                "         AS disposed "
                "FROM document_version dv "
                "JOIN document d ON d.id = dv.document_id "
                "LEFT JOIN anchor_record a ON a.version_id = dv.id "
                "WHERE dv.id = :v"
            ),
            {"v": version_id},
        )
    ).mappings().one()
    verdict = verify_version(VersionFacts(
        version_id=str(row["id"]),
        lifecycle_state=row["lifecycle_state"],
        recorded_sha256=row["sha256"],
        anchor=AnchorFacts(row["anchored"]) if row["anchored"] else None,
        live_sha256=blobs.digest_of_stored(row["sha256"]),
        disposition_recorded=bool(row["disposed"]),
    ))
    return verdict.state, dict(row)


@router.get("/versions/{version_id}/export")
async def export_version(
    version_id: str,
    request: Request,
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
):
    """One document, byte-exact, recorded.

    The digest travels with it in `X-Ordin-SHA256` so the recipient can check the copy
    against the case record without asking this system anything. That is the point of
    exporting rather than screenshotting.
    """
    now = datetime.now(timezone.utc)
    engine = request.app.state.engine
    blobs = request.app.state.blobs

    async with engine.begin() as conn:
        _, case_id, disclosure = await _resolve_version(
            conn, policy, subject, version_id, now
        )
        state, row = await _verdict(conn, blobs, version_id)
        if state is not VerificationState.VERIFIED:
            # Sentinel INTEG-01: an altered document is refused, never handed over as
            # evidence. A disposed one has no bytes by design, which is a different
            # sentence and the same refusal.
            raise HTTPException(status_code=409, detail=f"not_exportable:{state.value}")

        try:
            data = _read_blob(blobs, row["sha256"])
        except IntegrityMismatch:
            raise HTTPException(status_code=409, detail="integrity_mismatch") from None
        if data is None:
            raise HTTPException(status_code=409, detail="bytes_unavailable")

        await _record_export(
            conn, case_id=case_id, subject=subject, scope="version",
            disclosure=disclosure, row_count=1, byte_count=len(data),
        )
        await append_audit(
            conn,
            case_id=case_id,
            actor_id=subject.user_id,
            action=AuditAction.DOCUMENT_EXPORTED,
            object_type="version",
            object_id=version_id,
            at=now,
        )

    name = _clean_filename(f"{row['title']}-v{row['version_no']}.pdf")
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            # Not a courtesy. Without it the recipient has to trust the channel.
            "X-Ordin-SHA256": row["sha256"],
            "X-Ordin-Disclosure": disclosure.value,
            "Cache-Control": "no-store",
        },
    )


@router.get("/cases/{case_id}/export")
async def export_case(
    case_id: str,
    request: Request,
    subject: Subject = Depends(require_subject),
    policy: Policy = Depends(get_policy),
):
    """The bulk verb AR-17 names: every readable version of a case, in one archive.

    The archive carries a `manifest.json` listing **every** version the subject may
    receive, including the ones whose bytes were left out because they did not verify.
    A bundle that quietly contained fewer files than the case holds would make a
    tamper alert look like a short case file.
    """
    now = datetime.now(timezone.utc)
    engine = request.app.state.engine
    blobs = request.app.state.blobs

    try:
        uuid.UUID(case_id)
    except ValueError:
        raise NOT_FOUND

    async with engine.begin() as conn:
        disclosure = await _case_disclosure(conn, policy, subject, case_id, now)

        reference = (
            await conn.execute(
                sa.text("SELECT reference FROM case_record WHERE id = :c"), {"c": case_id}
            )
        ).scalar_one()

        documents = (
            await conn.execute(
                sa.text("SELECT id FROM document WHERE case_id = :c ORDER BY title"),
                {"c": case_id},
            )
        ).scalars().all()

        version_ids: list[str] = []
        for document_id in documents:
            version_ids.extend(
                await readable_version_ids(
                    conn, document_id=str(document_id), disclosure=disclosure
                )
            )

        if not version_ids:
            raise HTTPException(status_code=409, detail="nothing_to_export")
        if len(version_ids) > MAX_EXPORT_DOCUMENTS:
            raise HTTPException(
                status_code=413,
                detail=f"too_many_documents:{len(version_ids)}>{MAX_EXPORT_DOCUMENTS}",
            )

        entries: list[dict] = []
        byte_count = 0
        included_count = 0
        excluded = 0

        # **The archive is written as each document is read, not afterwards.**
        # Collecting every blob into a list and zipping at the end held the whole case
        # three times over - the raw bytes, the compressed archive, and the copy that
        # `getvalue()` makes - so a 64 MB cap on the raw bytes could peak near 190 MB
        # in a container limited to 256 MiB. That is the OOM the cap was sized to
        # prevent, arriving anyway. Streaming holds one document at a time.
        buffer = io.BytesIO()
        archive = zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED)
        seen: dict[str, int] = {}

        for version_id in version_ids:
            state, row = await _verdict(conn, blobs, version_id)
            name = _clean_filename(f"{row['title']}-v{row['version_no']}.pdf")
            included = state is VerificationState.VERIFIED

            data = None
            if included:
                try:
                    data = _read_blob(blobs, row["sha256"])
                except IntegrityMismatch:
                    included, state = False, VerificationState.MISMATCH
                if data is None:
                    included, state = False, VerificationState.UNAVAILABLE

            if included:
                byte_count += len(data)
                if byte_count > MAX_EXPORT_BYTES:
                    archive.close()
                    raise HTTPException(
                        status_code=413, detail=f"too_large:{MAX_EXPORT_BYTES}"
                    )
                # Two versions of two documents can share a title. Collapsing them onto
                # one archive entry would silently deliver fewer files than the manifest
                # promises, which is the failure the manifest exists to prevent.
                count = seen.get(name, 0)
                seen[name] = count + 1
                archive.writestr(
                    f"documents/{count}-{name}" if count else f"documents/{name}", data
                )
                included_count += 1
                # The compressed bytes are now in `buffer`; drop the plaintext copy
                # before reading the next document rather than at the end of the loop.
                del data
            else:
                excluded += 1

            entries.append({
                "version_id": version_id,
                "document_id": str(row["document_id"]),
                "version_no": row["version_no"],
                "filename": name,
                "sha256": row["sha256"],
                "integrity": state.value,
                "included": included,
            })

        record_id = await _record_export(
            conn, case_id=case_id, subject=subject, scope="case",
            disclosure=disclosure, row_count=included_count, byte_count=byte_count,
            excluded_count=excluded,
        )
        await append_audit(
            conn,
            case_id=case_id,
            actor_id=subject.user_id,
            action=AuditAction.CASE_EXPORTED,
            object_type="export",
            object_id=record_id,
            at=now,
        )

    manifest = {
        "case_reference": reference,
        "exported_at": now.isoformat(),
        "export_id": record_id,
        "disclosure": disclosure.value,
        "included": included_count,
        "excluded": excluded,
        "entries": entries,
        "note": (
            "Digests are of the exported bytes. Each file in this archive should hash "
            "to the sha256 recorded against it. Entries marked included=false were "
            "listed but not enclosed: their stored bytes did not match the anchored "
            "digest, or were not retained."
        ),
        "verification": (
            "The anchor store is hash-chained in the same database as the records it "
            "attests to; it is not an independent attestation (AR-4)."
        ),
    }

    # Written last because it names the export id, which only exists once the
    # accounting row is written. Zip entries carry no required order.
    archive.writestr("manifest.json", json.dumps(manifest, indent=2))
    archive.close()

    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{_clean_filename(reference)}-export.zip"'
            ),
            "X-Ordin-Export-Id": record_id,
            "X-Ordin-Disclosure": disclosure.value,
            "X-Ordin-Row-Count": str(included_count),
            "Cache-Control": "no-store",
        },
    )
