"""The detection engine and the hardening pass, as claims that can go red.

REDACT-05 is the one that matters. Before the detection engine, redaction covered the
labelled lines and nothing else, so a victim's surname repeated in the narrative went
to the grantee intact — and every existing scenario passed, because every one of them
checked the labelled field. This one reads the *derivative* and looks for the value
anywhere on the page.

INTEG-01 alters a document's bytes on disk and asks for the page. The only acceptable
answer is a refusal: an evidence system that renders a tampered page as though it were
evidence has failed at the one thing it exists for.
"""
import uuid
from pathlib import Path

import sqlalchemy as sa

from sentinel.registry import Severity, scenario

SLICE = "hardening"
ROOT = Path(__file__).resolve().parents[1]
STATEMENT = ROOT / "fixtures" / "corpus" / "statement-0011.pdf"
VALUES = ["Rukmini", "Deshmukh", "0900000111", "Banyan"]


async def _sign_in(ctx, key: str) -> None:
    response = await ctx.client.post("/session", json={"user_id": ctx.ids[key]})
    assert response.status_code == 200, f"could not open a session: {response.text}"


async def _ingest(ctx, filename: str, data: bytes) -> tuple[str, str]:
    """Push bytes through the real pipeline into the officer's case. (case, version)."""
    from infra.anchor import LocalAnchorStore
    from infra.esign import SimulatedESignProvider
    from infra.pipeline import Pipeline
    from infra.textsource import EmbeddedTextLayer

    await _sign_in(ctx, "officer")
    cases = (await ctx.client.get("/cases?limit=50")).json()
    assert cases, "the officer can see no case at all"
    case_id = cases[0]["id"]
    async with ctx.engine.begin() as conn:
        actor = (await conn.execute(sa.text("SELECT id FROM app_user LIMIT 1"))).scalar_one()
        result = await Pipeline(
            blobs=ctx.blobs, text_source=EmbeddedTextLayer(),
            signer=SimulatedESignProvider("sentinel"), anchors=LocalAnchorStore(),
        ).run(conn, case_id=uuid.UUID(case_id), filename=filename, data=data, actor_id=actor)
    assert result.ok, "the pipeline failed on the specimen"
    return case_id, result.version_id


@scenario(
    id="REDACT-05",
    invariant="8 - redaction removes every mention, not only the labelled one",
    setup=(
        "A victim statement names the victim in its labelled fields and again in the "
        "narrative - full name, surname alone, given name alone, phone and street. "
        "Redact it with the engine's defaults, then extract text from the derivative."
    ),
    expected="None of the values survive anywhere on the derivative's page.",
    severity=Severity.CRITICAL,
    slice_id=SLICE,
)
async def narrative_mentions_are_removed(ctx) -> str:
    from infra.redact import confirm_absent

    _, version_id = await _ingest(ctx, "sentinel-statement.pdf", STATEMENT.read_bytes())
    original_sha = None
    async with ctx.engine.connect() as conn:
        original_sha = (
            await conn.execute(
                sa.text("SELECT sha256 FROM document_version WHERE id = :v"), {"v": version_id}
            )
        ).scalar_one()
    original = ctx.blobs.get(original_sha)
    assert confirm_absent(original, VALUES) == VALUES, (
        "the specimen does not contain the values, so their absence would prove nothing"
    )

    made = await ctx.client.post(f"/versions/{version_id}/redact", json={})
    assert made.status_code == 201, f"redaction was refused: {made.status_code}"
    async with ctx.engine.connect() as conn:
        derivative_sha = (
            await conn.execute(
                sa.text("SELECT sha256 FROM document_version WHERE id = :v"),
                {"v": made.json()["version_id"]},
            )
        ).scalar_one()
    leaked = confirm_absent(ctx.blobs.get(derivative_sha), VALUES)
    assert not leaked, f"{len(leaked)} value(s) still extractable from the derivative"
    return (
        f"{made.json()['regions']} regions removed; none of {len(VALUES)} values "
        f"extractable, including the narrative mentions"
    )


@scenario(
    id="INTEG-01",
    invariant="5 - a document altered on disk is refused, never displayed as evidence",
    setup="Alter a version's stored bytes in place, then request its page and its verdict.",
    expected="The page is refused with integrity_mismatch; verify() reports MISMATCH.",
    severity=Severity.CRITICAL,
    slice_id=SLICE,
)
async def tampered_bytes_are_refused(ctx) -> str:
    import fitz

    # A throwaway document of its own, so tampering it cannot disturb another scenario.
    doc = fitz.open()
    doc.new_page().insert_text((72, 96), f"SPECIMEN - NOT A REAL RECORD {uuid.uuid4()}")
    data = doc.tobytes()
    doc.close()
    _, version_id = await _ingest(ctx, f"sentinel-tamper-{uuid.uuid4().hex[:8]}.pdf", data)

    async with ctx.engine.connect() as conn:
        sha = (
            await conn.execute(
                sa.text("SELECT sha256 FROM document_version WHERE id = :v"), {"v": version_id}
            )
        ).scalar_one()
    path = ctx.blobs._path(sha)
    before = path.read_bytes()
    assert (await ctx.client.get(f"/versions/{version_id}/page.png")).status_code == 200, (
        "the untampered page did not render, so a refusal later would prove nothing"
    )
    # One flipped bit mid-file. An earlier version replaced the word SPECIMEN in the raw
    # bytes, which matched nothing — the page text sits in a compressed stream — so the
    # "tampered" file was the original and the scenario went red for its own sake. The
    # assertion below is what stops a tamper that tampers nothing from ever passing.
    altered = bytearray(before)
    altered[len(altered) // 2] ^= 0x01
    assert bytes(altered) != before, "the tamper did not change the bytes"
    try:
        path.write_bytes(bytes(altered))
        page = await ctx.client.get(f"/versions/{version_id}/page.png")
        verdict = (await ctx.client.get(f"/versions/{version_id}/integrity")).json()
    finally:
        path.write_bytes(before)
    assert page.status_code == 409 and page.json().get("detail") == "integrity_mismatch", (
        f"the tampered page was served with status {page.status_code}"
    )
    assert verdict["state"] == "MISMATCH", f"verify() said {verdict['state']}"
    return "tampered page refused (409 integrity_mismatch); verify() reported MISMATCH"


@scenario(
    id="SEC-01",
    invariant="Transport - authorized responses are never cached, framed or sniffed",
    setup="Fetch an authorized API response and inspect its headers.",
    expected="no-store, nosniff, frame denial and a deny-all CSP on the response.",
    severity=Severity.HIGH,
    slice_id=SLICE,
)
async def responses_are_hardened(ctx) -> str:
    await _sign_in(ctx, "officer")
    response = await ctx.client.get("/cases")
    headers = {k.lower(): v for k, v in response.headers.items()}
    missing = [
        name for name, want in (
            ("cache-control", "no-store"),
            ("x-content-type-options", "nosniff"),
            ("x-frame-options", "DENY"),
            ("content-security-policy", "frame-ancestors 'none'"),
        )
        if want not in headers.get(name, "")
    ]
    assert not missing, f"missing or weak: {', '.join(missing)}"
    return "no-store, nosniff, DENY and a deny-all CSP present"


@scenario(
    id="SEC-02",
    invariant="Every view of a page is recorded in the audit chain",
    setup="Render a page, then read the audit trail for its document.",
    expected="A new document_viewed row naming the viewer.",
    severity=Severity.MEDIUM,
    slice_id=SLICE,
)
async def views_are_audited(ctx) -> str:
    async with ctx.engine.connect() as conn:
        before = (
            await conn.execute(
                sa.text("SELECT count(*) FROM audit_event WHERE action = 'document_viewed'")
            )
        ).scalar_one()
    _, version_id = await _ingest(ctx, "sentinel-statement.pdf", STATEMENT.read_bytes())
    assert (await ctx.client.get(f"/versions/{version_id}/page.png")).status_code == 200
    async with ctx.engine.connect() as conn:
        after = (
            await conn.execute(
                sa.text(
                    "SELECT count(*), max(actor_id) FILTER (WHERE object_id = :v) "
                    "FROM audit_event WHERE action = 'document_viewed'"
                ),
                {"v": version_id},
            )
        ).one()
    assert after[0] == before + 1, f"{after[0] - before} view rows appended, expected 1"
    assert after[1] == ctx.ids["officer"], "the view row does not name the viewer"
    return "one document_viewed row appended, naming the viewer"
