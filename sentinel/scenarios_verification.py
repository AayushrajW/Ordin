"""Slice 5b's contribution to Sentinel, plus the first scenario over the audit chain.

The claim VERIFY-01 makes is the one the whole product rests on: **no machine in this
system can mark evidence verified.** It is worth watching rather than asserting,
because the natural way to build a verification screen — let the API set `status` from
whatever the client sends — passes every other test in the build.

VERIFY-02 is the one that would have been wrong. A purpose-limited grantee passes the
case-level filter, so a commit route that checked only "may you read this case?" would
let them sign off on values extracted from a document they are forbidden to read.
"""
import uuid

import sqlalchemy as sa

from sentinel.registry import Severity, scenario

SLICE = "5b"


async def _sign_in(ctx, key: str) -> None:
    response = await ctx.client.post("/session", json={"user_id": ctx.ids[key]})
    assert response.status_code == 200, f"could not open a session: {response.text}"


async def _ensure_document(ctx) -> tuple[str, str]:
    """Push a specimen through the real pipeline. Returns (case_id, version_id).

    **It always runs the pipeline** rather than reusing whatever document happens to
    be in the case. An earlier version took the first document it found, which after
    slice 7's scenarios ran was a hand-inserted parent with a placeholder digest and
    no bytes in the store — so VERIFY-01 was committing a row that no extractor had
    produced, and reporting that as proof that the pipeline drafts. The scenario
    passed and meant nothing, which is the exact failure the registry docstring names.

    Running it every time is safe and is itself part of the claim: the pipeline is
    idempotent, so the second call produces no second version, field set or anchor.
    """
    from pathlib import Path

    from infra.anchor import LocalAnchorStore
    from infra.esign import SimulatedESignProvider
    from infra.pipeline import Pipeline
    from infra.textsource import EmbeddedTextLayer

    root = Path(__file__).resolve().parents[1]

    await _sign_in(ctx, "officer")
    cases = (await ctx.client.get("/cases?limit=50")).json()
    assert cases, "the officer can see no case at all; the seed is not what it was"
    case_id = cases[0]["id"]

    async with ctx.engine.begin() as conn:
        actor = (
            await conn.execute(sa.text("SELECT id FROM app_user LIMIT 1"))
        ).scalar_one()
        pipeline = Pipeline(
            blobs=ctx.blobs,
            # The text layer rather than Tesseract: this scenario is about who may
            # write `verified`, and a real OCR pass would add half a minute to the
            # demo run without changing what it proves. OCR accuracy is measured
            # separately by `tasks.py evaluate`.
            text_source=EmbeddedTextLayer(),
            signer=SimulatedESignProvider("sentinel"),
            anchors=LocalAnchorStore(),
        )
        result = await pipeline.run(
            conn,
            case_id=uuid.UUID(case_id),
            filename="verification-specimen.pdf",
            data=(root / "fixtures" / "corpus" / "complaint-0001.pdf").read_bytes(),
            actor_id=actor,
        )
    assert result.ok, f"the pipeline failed: {[s.stage for s in result.stages]}"
    return case_id, result.version_id


@scenario(
    id="VERIFY-01",
    invariant="9 - AI output is always draft; only an explicit human commit verifies",
    setup="A document runs the full pipeline, then a designated officer commits one field.",
    expected="Nothing is verified until the human acts, and the row then names them.",
    severity=Severity.CRITICAL,
    slice_id=SLICE,
)
async def only_a_human_commit_writes_verified(ctx) -> str:
    """Runs on a specimen minted for this run, so there is always a fresh draft.

    An earlier version reused the demo document, and on a second run found the field a
    human had committed during the first — then reported that the *pipeline* had
    written `verified`. The claim is about what the pipeline emits, so it needs a
    version the pipeline has only just produced.
    """
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 96), "SPECIMEN - NOT A REAL RECORD", fontsize=11)
    page.insert_text((72, 120), f"Reference: SNT/{uuid.uuid4().hex[:10]}", fontsize=10)
    page.insert_text((72, 138), "Complainant Name: Specimen Person", fontsize=10)
    data = doc.tobytes()
    doc.close()

    from infra.anchor import LocalAnchorStore
    from infra.esign import SimulatedESignProvider
    from infra.pipeline import Pipeline
    from infra.textsource import EmbeddedTextLayer

    await _sign_in(ctx, "officer")
    case_id = (await ctx.client.get("/cases?limit=50")).json()[0]["id"]
    async with ctx.engine.begin() as conn:
        actor = (await conn.execute(sa.text("SELECT id FROM app_user LIMIT 1"))).scalar_one()
        result = await Pipeline(
            blobs=ctx.blobs, text_source=EmbeddedTextLayer(),
            signer=SimulatedESignProvider("sentinel"), anchors=LocalAnchorStore(),
        ).run(conn, case_id=uuid.UUID(case_id), filename="sentinel-verify.pdf",
              data=data, actor_id=actor)
    version_id = result.version_id

    fields = (await ctx.client.get(f"/versions/{version_id}/fields")).json()
    machine = [f for f in fields if f["source"] != "human"]
    assert machine, "the pipeline extracted nothing, so this proves nothing"
    assert all(f["status"] == "draft" for f in machine), (
        "the pipeline produced a field already marked verified"
    )

    target = next(f for f in machine if f["status"] == "draft")
    response = await ctx.client.post(f"/fields/{target['id']}/verify")
    assert response.status_code == 200, f"the commit was refused: {response.text}"
    committed = response.json()
    assert committed["status"] == "verified"
    assert committed["verified_by"] == ctx.ids["officer"], (
        "the row does not name the human who committed it"
    )
    return (
        f"{len(machine)} machine field(s) drafted by the pipeline; "
        f"1 verified only after the officer committed it"
    )


@scenario(
    id="VERIFY-02",
    invariant="ADR 0014 - attestation requires the disclosure class that may read the original",
    setup="A grantee holding a purpose-limited grant tries to verify a field on the original.",
    expected="404, and the field is still a draft afterwards.",
    severity=Severity.CRITICAL,
    slice_id=SLICE,
)
async def a_redacted_subject_cannot_attest(ctx) -> str:
    _, version_id = await _ensure_document(ctx)
    fields = (await ctx.client.get(f"/versions/{version_id}/fields")).json()
    draft = next((f for f in fields if f["status"] == "draft"), None)
    if draft is None:
        # VERIFY-01 may have run first and committed the only draft. Enter a fresh
        # field to attest to rather than reporting a pass with nothing to refuse.
        entered = await ctx.client.post(
            f"/versions/{version_id}/fields",
            json={"field_key": "sentinel_probe", "value": "specimen value"},
        )
        assert entered.status_code == 201, entered.text
        draft = entered.json()

    await ctx.client.delete("/session")
    await _sign_in(ctx, "grantee")
    response = await ctx.client.post(f"/fields/{draft['id']}/verify")
    assert response.status_code == 404, (
        f"the grantee's commit returned {response.status_code}, not 404"
    )

    async with ctx.engine.connect() as conn:
        author = (
            await conn.execute(
                sa.text("SELECT verified_by FROM extracted_field WHERE id = :i"),
                {"i": draft["id"]},
            )
        ).scalar_one()
    assert str(author or "") != ctx.ids["grantee"], "the grantee's id reached verified_by"
    return "commit refused with 404; the field's authorship is untouched"


@scenario(
    id="VERIFY-03",
    invariant="8 - unauthorised roles never receive original bytes on any code path",
    setup=(
        "A grantee lists the documents of a case they hold a purpose-limited grant on, "
        "after an original has been processed into it."
    ),
    expected="Every version offered is a derivative. The original's id appears nowhere.",
    severity=Severity.HIGH,
    slice_id=SLICE,
)
async def a_grantee_is_never_offered_an_original(ctx) -> str:
    """Asserts the shape of the listing, not its length.

    An earlier version of this scenario asserted the grantee saw *no* documents,
    which was true only until another scenario redacted something into the same case
    — and then reported the system broken for doing exactly the right thing. The
    claim worth making is narrower and does not depend on what else ran: whatever
    they are shown, none of it is an original.
    """
    case_id, original_version = await _ensure_document(ctx)
    await ctx.client.delete("/session")
    await _sign_in(ctx, "grantee")

    documents = (await ctx.client.get(f"/cases/{case_id}/documents")).json()
    offered = [v for d in documents for v in d["versions"]]
    assert all(v["is_derivative"] for v in offered), (
        f"{sum(not v['is_derivative'] for v in offered)} original version(s) offered "
        f"to a purpose-limited grantee"
    )
    assert original_version not in [v["id"] for v in offered], (
        "the original processed in this scenario was offered to the grantee"
    )
    # And naming it directly is refused too, which is the same claim from the other
    # side: the listing hiding it would be worth little if the id still worked.
    direct = await ctx.client.get(f"/versions/{original_version}/fields")
    assert direct.status_code == 404, f"the original's fields returned {direct.status_code}"
    return (
        f"{len(offered)} version(s) offered, all derivatives; "
        f"the original's id returns 404 when named directly"
    )


@scenario(
    id="AUDIT-01",
    invariant="10 - audit rows are append-only and hash-chained",
    setup=(
        "Recompute the whole audit chain from genesis over every row in the table. "
        "Run this after `tasks.py fresh && seed`: rows written by a hand-rolled INSERT "
        "in an earlier session would legitimately report broken."
    ),
    expected="Every row's hash matches its own contents and its predecessor.",
    severity=Severity.HIGH,
    slice_id=SLICE,
)
async def the_audit_chain_verifies_end_to_end(ctx) -> str:
    from datetime import timezone

    from domain.audit import AuditChainStatus, AuditPayload, verify_chain
    from domain.enums import AuditAction

    async with ctx.engine.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT case_id, actor_id, action, object_type, object_id, utc_ts, "
                    "       row_hash FROM audit_event ORDER BY seq"
                )
            )
        ).mappings().all()

    assert rows, (
        "the audit table is empty, so this scenario proves nothing - run VERIFY-01 first"
    )
    result = verify_chain(
        [
            (
                AuditPayload(
                    case_id=r["case_id"],
                    actor_id=r["actor_id"],
                    action=AuditAction(r["action"]),
                    object_type=r["object_type"],
                    object_id=r["object_id"],
                    utc_ts=r["utc_ts"].astimezone(timezone.utc).isoformat(),
                ),
                r["row_hash"],
            )
            for r in rows
        ]
    )
    assert result.status is AuditChainStatus.VERIFIED, (
        f"chain broken at row {result.broken_at}: {result.detail}"
    )
    # Said out loud because the pitch must not overstate it: this is tamper-evidence
    # against in-place edits, not proof. Accepted risk AR-4.
    return f"{len(rows)} rows recomputed from genesis; unkeyed digest, no external witness"
