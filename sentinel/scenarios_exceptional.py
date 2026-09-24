"""Break-glass, export and disposal, as claims that can go red.

Three of the loudest things this system says about itself live here.

  SEAL-01   the seal has an exception and the exception is not a master key
  EXPORT-01 a document that does not verify is never handed over as evidence
  DISPOSE-01 a lawfully destroyed document is not reported as a tampered one

SEAL-01 is the one worth watching. Break-glass is the kind of feature that looks
responsible in a demo and is catastrophic if the predicate is read by the wrong rule:
a written excuse that opens any sealed case in the system. The scenario writes a live
declaration for a subject with **no designation** and asserts they are still refused,
so the claim "it removes an obstacle, it is never a route in" is something a judge can
watch fail rather than something the README asserts.
"""
import uuid

import sqlalchemy as sa

from sentinel.registry import Severity, scenario

SLICE = "exceptional"

JUSTIFICATION = (
    "Sentinel scenario: a bounded declaration written so the seal can be shown to "
    "have an exception that is recorded rather than worked around."
)


async def _sign_in(ctx, key: str) -> None:
    response = await ctx.client.post("/session", json={"user_id": ctx.ids[key]})
    assert response.status_code == 200, f"could not open a session: {response.text}"


async def _designate(ctx, *, case_id: str, user_id: str) -> str:
    assignment_id = str(uuid.uuid4())
    async with ctx.engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO case_assignment (id, case_id, user_id, valid_from, "
                "valid_to, assigned_by) "
                "VALUES (:i, :c, :u, now() - interval '1 day', NULL, :u)"
            ),
            {"i": assignment_id, "c": case_id, "u": user_id},
        )
    return assignment_id


# **No cleanup helper, deliberately.** An earlier version of this file reached for the
# OWNER role from inside a scenario to DELETE rows from `break_glass_access` between
# runs. Two things were wrong with that. Sentinel exercises the running application as
# the application - a scenario that needs privileges the app does not have is testing
# something the app cannot do. And `break_glass_access` is append-only by grant
# (migration 0013) precisely so a declaration cannot be tidied away afterwards; a helper
# that tidies them away is a working demonstration of the attack the grant prevents. It
# also deleted by (case, actor), so it removed declarations it had not created.
#
# The scenarios are made independent instead: SEAL-02 registers its own sealed case each
# run, and SEAL-01's declaration is harmless to leave behind - the whole point of SEAL-01
# is that a declaration with no designation behind it opens nothing.


@scenario(
    id="SEAL-01",
    invariant="ADR 0029 - break-glass removes an obstacle, it is never a ground for access",
    setup=(
        "Write a live, unexpired break-glass declaration for an officer who holds no "
        "designation on the sealed case, then have them request it."
    ),
    expected=(
        "404, identical to a case that does not exist. The declaration lifts the seal "
        "from a path the subject already had and creates no path of its own."
    ),
    severity=Severity.CRITICAL,
    slice_id=SLICE,
)
async def break_glass_is_not_a_master_key(ctx) -> str:
    record_id = str(uuid.uuid4())
    async with ctx.engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO break_glass_access (id, case_id, actor_id, justification, "
                "expires_at) VALUES (:i, :c, :u, :j, now() + interval '1 hour')"
            ),
            {"i": record_id, "c": ctx.ids["sealed_case"], "u": ctx.ids["officer"],
             "j": JUSTIFICATION},
        )

    await _sign_in(ctx, "officer")
    denied = await ctx.client.get(f"/cases/{ctx.ids['sealed_case']}")
    missing = await ctx.client.get(f"/cases/{uuid.uuid4()}")

    assert denied.status_code == 404, (
        f"a live break-glass admitted a subject with no designation "
        f"({denied.status_code}); it is acting as a ground for access"
    )
    assert denied.json() == missing.json(), (
        "a denied case is distinguishable from a missing one - existence oracle"
    )
    return (
        "a live declaration on a sealed case opened nothing for an undesignated "
        "officer, and the refusal is byte-identical to a missing case"
    )


@scenario(
    id="SEAL-02",
    invariant="ADR 0029 - the exception is available, bounded, and costs a written record",
    setup=(
        "Designate an officer with ordinary clearance on the sealed case. They are "
        "refused, declare a justification, and ask again."
    ),
    expected=(
        "Refused, then admitted, with the justification stored in its own table and "
        "only its id on the audit chain."
    ),
    severity=Severity.HIGH,
    slice_id=SLICE,
)
async def the_seal_has_a_recorded_exception(ctx) -> str:
    # A sealed case of its own, registered by the officer whose clearance reaches a
    # seal - which is also the only officer `create_case` will let register one, since
    # it refuses a case the author could not then open. The ordinary-clearance officer
    # is designated on it afterwards, which is exactly the situation break-glass is for:
    # a senior officer opens a sealed file and assigns an investigator who cannot read
    # it. Fresh each run, so this scenario shares no state with SEAL-01 and needs no
    # cleanup.
    await _sign_in(ctx, "cleared")
    created = await ctx.client.post(
        "/cases",
        json={"reference": f"SNT-{uuid.uuid4().hex[:8].upper()}", "sealed": True},
    )
    assert created.status_code == 201, f"could not register a sealed case: {created.text}"
    case_id = created.json()["case_id"]
    await _designate(ctx, case_id=case_id, user_id=ctx.ids["officer"])

    await _sign_in(ctx, "officer")

    before = await ctx.client.get(f"/cases/{case_id}")
    assert before.status_code == 404, (
        f"the sealed case was readable without clearance ({before.status_code})"
    )

    declared = await ctx.client.post(
        f"/cases/{case_id}/break-glass",
        json={"justification": JUSTIFICATION, "minutes": 60},
    )
    assert declared.status_code == 201, f"could not declare: {declared.text}"

    after = await ctx.client.get(f"/cases/{case_id}")
    assert after.status_code == 200, (
        f"the glass was broken and the door did not open ({after.status_code})"
    )

    async with ctx.engine.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "SELECT action, object_type, object_id FROM audit_event "
                    "WHERE action = 'seal_break_glass' ORDER BY seq DESC LIMIT 1"
                )
            )
        ).mappings().one()
        stored = (
            await conn.execute(
                sa.text("SELECT justification FROM break_glass_access WHERE id = :i"),
                {"i": row["object_id"]},
            )
        ).scalar_one()

    assert stored == JUSTIFICATION, "the chain row does not point at the justification"
    # Invariant 4: the words are in the table, never in the payload.
    assert JUSTIFICATION[:30] not in " ".join(str(v) for v in row.values())
    return (
        "refused, then admitted for 60 minutes; the chain carries the record's id and "
        "the justification lives off it"
    )


async def _a_processed_version(ctx) -> tuple[str, str, str]:
    """Push one document through the real pipeline. Returns (case, version, digest)."""
    import fitz

    from infra.anchor import LocalAnchorStore
    from infra.esign import SimulatedESignProvider
    from infra.pipeline import Pipeline
    from infra.textsource import EmbeddedTextLayer

    await _sign_in(ctx, "officer")
    case_id = ctx.ids["primary_case"]

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 96), f"SPECIMEN - NOT A REAL RECORD {uuid.uuid4()}")
    data = document.tobytes()
    document.close()

    async with ctx.engine.begin() as conn:
        actor = (
            await conn.execute(sa.text("SELECT id FROM app_user LIMIT 1"))
        ).scalar_one()
        result = await Pipeline(
            blobs=ctx.blobs,
            text_source=EmbeddedTextLayer(),
            signer=SimulatedESignProvider("sentinel"),
            anchors=LocalAnchorStore(),
        ).run(
            conn,
            case_id=uuid.UUID(case_id),
            filename=f"sentinel-{uuid.uuid4().hex[:8]}.pdf",
            data=data,
            actor_id=actor,
        )
    assert result.ok, "the pipeline failed on the specimen"
    return case_id, result.version_id, result.content_sha256


@scenario(
    id="EXPORT-01",
    invariant="Export is byte-exact, counted, and refused when the document does not verify",
    setup=(
        "Export one processed document and hash what came back. Then alter the stored "
        "file and ask for it again."
    ),
    expected=(
        "The first export hashes to the anchored digest and is counted in "
        "export_record. The second is refused outright."
    ),
    severity=Severity.CRITICAL,
    slice_id=SLICE,
)
async def export_is_evidential_and_accounted(ctx) -> str:
    import hashlib

    case_id, version_id, digest = await _a_processed_version(ctx)

    taken = await ctx.client.get(f"/versions/{version_id}/export")
    assert taken.status_code == 200, f"export refused: {taken.text}"
    assert hashlib.sha256(taken.content).hexdigest() == digest, (
        "the exported bytes do not hash to the anchored digest, so a recipient cannot "
        "verify the copy against the case record - the export is not evidential"
    )

    async with ctx.engine.connect() as conn:
        counted = (
            await conn.execute(
                sa.text(
                    "SELECT row_count, disclosure, scope FROM export_record "
                    "ORDER BY exported_at DESC LIMIT 1"
                )
            )
        ).mappings().one()
    assert counted["row_count"] == 1 and counted["scope"] == "version", counted

    # Now alter the stored bytes and ask again.
    path = ctx.blobs.root / digest[:2] / digest[2:4] / digest
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 0x01
    path.write_bytes(bytes(raw))

    refused = await ctx.client.get(f"/versions/{version_id}/export")
    assert refused.status_code == 409, (
        f"an altered document was exported as evidence ({refused.status_code})"
    )
    assert refused.json()["detail"].startswith("not_exportable:"), refused.json()
    return (
        f"{len(taken.content)} bytes exported and hashed to the anchor, counted in "
        "export_record; one flipped bit made the next export a refusal"
    )


@scenario(
    id="DISPOSE-01",
    invariant="5 - a lawfully disposed document is not a tampered one",
    setup=(
        "Dispose a processed version, then ask for its integrity verdict and its "
        "derived text."
    ),
    expected=(
        "DISPOSED_ANCHOR_ONLY, never MISMATCH. The bytes and the OCR text are gone; "
        "the anchor and the disposition record remain."
    ),
    severity=Severity.CRITICAL,
    slice_id=SLICE,
)
async def disposal_is_not_tampering(ctx) -> str:
    case_id, version_id, digest = await _a_processed_version(ctx)
    path = ctx.blobs.root / digest[:2] / digest[2:4] / digest
    assert path.exists(), "the pipeline stored nothing, so this would prove nothing"

    disposed = await ctx.client.post(
        f"/versions/{version_id}/dispose", json={"basis": "retention_expiry"}
    )
    assert disposed.status_code == 200, f"disposal refused: {disposed.text}"

    verdict = (await ctx.client.get(f"/versions/{version_id}/integrity")).json()
    assert verdict["state"] == "DISPOSED_ANCHOR_ONLY", (
        f"a lawfully disposed document reports {verdict['state']}. Reporting MISMATCH "
        "for a lawful disposal is not a cosmetic bug - it is a claim that evidence was "
        "tampered with"
    )
    assert not path.exists(), "the bytes survived a disposal"

    async with ctx.engine.connect() as conn:
        derived = (
            await conn.execute(
                sa.text("SELECT count(*) FROM ocr_text WHERE version_id = :v"),
                {"v": version_id},
            )
        ).scalar_one()
        recorded = (
            await conn.execute(
                sa.text("SELECT basis FROM disposition WHERE version_id = :v"),
                {"v": version_id},
            )
        ).scalar_one()
    assert derived == 0, (
        "the OCR text of a destroyed document is still stored and still searchable "
        "(threat AR-13) - this is a disposal in name only"
    )
    return (
        f"bytes destroyed and derived text removed; verdict DISPOSED_ANCHOR_ONLY with "
        f"basis {recorded!r} and the anchor intact"
    )
