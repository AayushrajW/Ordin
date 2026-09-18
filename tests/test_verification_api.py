"""Slice 5b's acceptance criterion: a human commit is the only thing that writes
`verified`, and it is reachable.

Invariant 9 has been true since slice 5a and enforced by `ck_verified_names_a_human`
since migration 0006 — but until this slice nothing in the running system could
actually perform the commit. A constraint proving that only a human *may* write
`verified` while no human *can* is a strange sort of compliance, and it is the reason
5b is Tier A rather than polish.

The test that earns its place here is
`test_a_grantee_holding_only_a_redacted_view_cannot_verify`. Verification is an
attestation about the contents of a document. A purpose-limited grantee receives the
derivative precisely because they may not read the original, so letting them attest to
its extracted values would be both an authorization bug and a nonsense: they would be
vouching for text they are not permitted to see. The route therefore requires
disclosure ORIGINAL, not merely a readable case (docs/adr/0014).
"""
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from api.main import create_app
from domain.audit import GENESIS_HASH, AuditPayload, compute_row_hash
from domain.enums import AuditAction
from infra.anchor import LocalAnchorStore
from infra.blobstore import LocalBlobStore
from infra.esign import SimulatedESignProvider
from infra.pipeline import Pipeline
from infra.subject_provider import COOKIE_NAME
from infra.textsource import EmbeddedTextLayer
from infra.tables import app_user, case_record

pytestmark = pytest.mark.requires_db

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "corpus" / "complaint-0001.pdf"


@pytest.fixture
async def api(live_settings, tmp_path):
    """Seed, push one real document through the golden thread, then serve it.

    The document is created by the pipeline rather than by hand-written INSERTs, so
    the fields under test are genuinely machine-extracted drafts carrying spans —
    which is what makes "only a human commit writes verified" a claim about the
    system rather than about the fixture.
    """
    import seed as seed_module

    await seed_module.seed()

    owner = create_async_engine(live_settings.owner_dsn)
    blobs = tmp_path / "blobs"
    async with owner.connect() as conn:
        case_a = (
            await conn.execute(
                sa.select(case_record.c.id).where(case_record.c.reference == "VRN-N/2026/0001")
            )
        ).scalar_one()
        actor = (
            await conn.execute(
                sa.select(app_user.c.id).where(app_user.c.display_name.like("SHO Rahul%"))
            )
        ).scalar_one()
        pipeline = Pipeline(
            blobs=LocalBlobStore(blobs),
            text_source=EmbeddedTextLayer(),
            signer=SimulatedESignProvider("test-secret"),
            anchors=LocalAnchorStore(),
        )
        result = await pipeline.run(
            conn,
            case_id=case_a,
            filename="complaint-0001.pdf",
            data=FIXTURE.read_bytes(),
            actor_id=actor,
        )
        await conn.commit()
    await owner.dispose()

    app = create_app(live_settings)
    engine = create_async_engine(live_settings.app_dsn)
    app.state.engine = engine
    # The API reads bytes back through the same store the pipeline wrote to.
    app.state.blobs = LocalBlobStore(blobs)

    ids = {"case": str(case_a), "version": result.version_id, "document": result.document_id}
    async with engine.connect() as conn:
        for fragment, key in (
            ("SI Kavya", "officer"),
            ("PP Arjun", "grantee"),
            ("PP Meera", "lapsed"),
        ):
            ids[key] = str(
                (
                    await conn.execute(
                        sa.select(app_user.c.id).where(
                            app_user.c.display_name.like(f"{fragment}%")
                        )
                    )
                ).scalar_one()
            )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        yield client, ids, engine
    await engine.dispose()


async def sign_in(client, user_id: str) -> None:
    assert (await client.post("/session", json={"user_id": user_id})).status_code == 200


async def first_draft_field(client, version_id: str) -> dict:
    fields = (await client.get(f"/versions/{version_id}/fields")).json()
    drafts = [f for f in fields if f["status"] == "draft"]
    assert drafts, "the pipeline produced no draft fields, so this file proves nothing"
    return drafts[0]


# --- the surface refuses without a session -----------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/cases/{case}/documents"),
        ("get", "/documents/{document}"),
        ("get", "/versions/{version}/fields"),
        ("get", "/versions/{version}/text"),
        ("get", "/versions/{version}/page.png"),
        ("post", "/versions/{version}/fields"),
    ],
)
async def test_every_new_route_refuses_without_a_session(api, method, path):
    client, ids, _ = api
    url = path.format(**ids)
    response = await getattr(client, method)(url) if method == "get" else await client.post(
        url, json={"field_key": "k", "value": "v"}
    )
    assert response.status_code == 401


# --- reading -----------------------------------------------------------------


async def test_a_designated_officer_sees_the_document_and_its_draft_fields(api):
    client, ids, _ = api
    await sign_in(client, ids["officer"])

    documents = (await client.get(f"/cases/{ids['case']}/documents")).json()
    assert [d["id"] for d in documents] == [ids["document"]]
    assert documents[0]["disclosure"] == "original"

    fields = (await client.get(f"/versions/{ids['version']}/fields")).json()
    assert fields, "no extracted fields came back"
    assert all(f["status"] == "draft" for f in fields), (
        "the pipeline wrote something already verified, which invariant 9 forbids"
    )
    assert all(f["source_span_start"] is not None for f in fields)


async def test_an_unreadable_case_and_a_missing_one_are_byte_identical(api):
    """The oracle test, repeated on the new surface.

    Case B is real and not readable by this officer. A response that differs from the
    one for a random uuid confirms the case exists (threat INS-04), and every route
    added in this slice is a new opportunity to get that wrong.
    """
    client, ids, engine = api
    await sign_in(client, ids["officer"])
    async with engine.connect() as conn:
        other = str(
            (
                await conn.execute(
                    sa.select(case_record.c.id).where(
                        case_record.c.reference == "VRN-S/2026/0002"
                    )
                )
            ).scalar_one()
        )

    real_but_forbidden = await client.get(f"/cases/{other}/documents")
    pure_fiction = await client.get(f"/cases/{uuid.uuid4()}/documents")
    assert real_but_forbidden.status_code == pure_fiction.status_code == 404
    assert real_but_forbidden.content == pure_fiction.content


async def test_the_page_image_is_refused_outside_the_disclosure_class(api):
    """The grantee may read the case and may not read this version's bytes.

    There is no derivative in this fixture, so a purpose-limited grantee has nothing
    to receive — and "nothing" must be a 404, not the original page.
    """
    client, ids, _ = api
    await sign_in(client, ids["grantee"])
    response = await client.get(f"/versions/{ids['version']}/page.png")
    assert response.status_code == 404

    await client.delete("/session")
    await sign_in(client, ids["officer"])
    allowed = await client.get(f"/versions/{ids['version']}/page.png")
    assert allowed.status_code == 200
    assert allowed.headers["content-type"] == "image/png"
    assert allowed.content[:8] == b"\x89PNG\r\n\x1a\n"


# --- the commit --------------------------------------------------------------


async def test_a_human_commit_is_what_writes_verified(api):
    client, ids, engine = api
    await sign_in(client, ids["officer"])
    field = await first_draft_field(client, ids["version"])

    async with engine.connect() as conn:
        before = (
            await conn.execute(
                sa.text("SELECT count(*) FROM extracted_field WHERE status = 'verified'")
            )
        ).scalar_one()
    assert before == 0, "something wrote verified before any human did"

    response = await client.post(f"/fields/{field['id']}/verify")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "verified"
    assert body["verified_by"] == ids["officer"]

    async with engine.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "SELECT status, verified_by, verified_at, value "
                    "FROM extracted_field WHERE id = :i"
                ),
                {"i": field["id"]},
            )
        ).mappings().one()
    assert row["status"] == "verified"
    assert str(row["verified_by"]) == ids["officer"]
    assert row["verified_at"] is not None
    assert row["value"] == field["value"], "accepting a field must not rewrite its value"


async def test_the_commit_appends_a_correctly_linked_audit_row(api):
    """The commit is the first thing in the build that writes the audit chain.

    The assertion is linkage against the head that existed at the time, not a
    verification of the whole table. `audit_event` has no DELETE grant and `seed.py`
    deliberately spares it, so a long-lived development database accumulates rows
    from every test that ever ran — including ones that write deliberately arbitrary
    hashes to prove the REVOKE bites. Verifying the whole table here would make this
    test fail for a reason that has nothing to do with the commit route.
    """
    client, ids, engine = api
    await sign_in(client, ids["officer"])
    fields = [f for f in (await client.get(f"/versions/{ids['version']}/fields")).json()
              if f["status"] == "draft"]
    assert len(fields) >= 2, "need two drafts to prove the second row links to the first"

    async with engine.connect() as conn:
        head = (
            await conn.execute(
                sa.text("SELECT row_hash FROM audit_event ORDER BY seq DESC LIMIT 1")
            )
        ).scalar_one_or_none() or GENESIS_HASH

    for field in fields[:2]:
        assert (await client.post(f"/fields/{field['id']}/verify")).status_code == 200

    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT case_id, actor_id, action, object_type, object_id, utc_ts, "
                    "       prev_row_hash, row_hash FROM audit_event "
                    "ORDER BY seq DESC LIMIT 2"
                )
            )
        ).mappings().all()
    appended = list(reversed(rows))

    assert appended[0]["prev_row_hash"] == head, "the append did not commit to the head"
    assert appended[1]["prev_row_hash"] == appended[0]["row_hash"], "the two rows do not link"

    prev = head
    for row, field in zip(appended, fields[:2]):
        assert row["action"] == AuditAction.FIELD_VERIFIED.value
        assert row["actor_id"] == ids["officer"]
        assert row["object_id"] == field["id"]
        # Invariant 4 and 12: identifiers only. The extracted value never reaches the
        # chain, and neither does the field key it was found under.
        assert field["value"] not in str(dict(row))
        expected = compute_row_hash(
            prev,
            AuditPayload(
                case_id=row["case_id"],
                actor_id=row["actor_id"],
                action=AuditAction(row["action"]),
                object_type=row["object_type"],
                object_id=row["object_id"],
                utc_ts=row["utc_ts"].astimezone(timezone.utc).isoformat(),
            ),
        )
        assert row["row_hash"] == expected, (
            "the stored hash does not match its own contents - the timestamp most "
            "likely does not round-trip through timestamptz in the form it was hashed in"
        )
        prev = row["row_hash"]


async def test_a_grantee_holding_only_a_redacted_view_cannot_verify(api):
    """docs/adr/0014. The case is readable; the attestation is not available.

    Note what would happen without the disclosure check: the grantee passes the slice
    3 case filter, so a route that checked only "may you read this case?" would let
    them sign off on the contents of a document they are forbidden to read.
    """
    client, ids, engine = api
    await sign_in(client, ids["officer"])
    field = await first_draft_field(client, ids["version"])
    await client.delete("/session")

    await sign_in(client, ids["grantee"])
    response = await client.post(f"/fields/{field['id']}/verify")
    assert response.status_code == 404

    async with engine.connect() as conn:
        status = (
            await conn.execute(
                sa.text("SELECT status FROM extracted_field WHERE id = :i"), {"i": field["id"]}
            )
        ).scalar_one()
    assert status == "draft"


async def test_a_subject_with_lapsed_clearance_cannot_verify(api):
    """Meera holds a live, lawfully issued grant and a lapsed clearance.

    The three validity clocks intersect rather than union (threat AZM-06), and the
    commit route must inherit that rather than re-deriving it.
    """
    client, ids, _ = api
    await sign_in(client, ids["officer"])
    field = await first_draft_field(client, ids["version"])
    await client.delete("/session")

    await sign_in(client, ids["lapsed"])
    assert (await client.post(f"/fields/{field['id']}/verify")).status_code == 404


async def test_verifying_twice_keeps_the_first_author(api):
    """A retry is not a second attestation, and must not silently reassign authorship."""
    client, ids, engine = api
    await sign_in(client, ids["officer"])
    field = await first_draft_field(client, ids["version"])

    assert (await client.post(f"/fields/{field['id']}/verify")).status_code == 200
    async with engine.connect() as conn:
        first = (
            await conn.execute(
                sa.text("SELECT verified_by, verified_at FROM extracted_field WHERE id = :i"),
                {"i": field["id"]},
            )
        ).mappings().one()

    await client.delete("/session")
    await sign_in(client, ids["grantee"])
    assert (await client.post(f"/fields/{field['id']}/verify")).status_code == 404

    await client.delete("/session")
    await sign_in(client, ids["officer"])
    assert (await client.post(f"/fields/{field['id']}/verify")).status_code == 200

    async with engine.connect() as conn:
        second = (
            await conn.execute(
                sa.text("SELECT verified_by, verified_at FROM extracted_field WHERE id = :i"),
                {"i": field["id"]},
            )
        ).mappings().one()
    assert second["verified_by"] == first["verified_by"]
    assert second["verified_at"] == first["verified_at"]


# --- correction and manual entry ---------------------------------------------


async def test_a_correction_records_a_human_field_and_leaves_the_machine_one_alone(api):
    """Provenance survives disagreement.

    The machine said one thing and a human says another. Overwriting the extracted
    value would destroy the only record of what the extractor actually produced,
    which is the evidence that the extractor needs correcting. Invariant 7's fields
    exist to make that difference legible, so a correction is a *new row* with
    `source='human'`, not an UPDATE.
    """
    client, ids, engine = api
    await sign_in(client, ids["officer"])
    field = await first_draft_field(client, ids["version"])

    response = await client.post(
        f"/versions/{ids['version']}/fields",
        json={"field_key": field["field_key"], "value": "Corrected By Hand"},
    )
    assert response.status_code == 201, response.text
    human = response.json()
    assert human["source"] == "human"
    assert human["status"] == "verified"
    assert human["entered_by"] == ids["officer"]
    assert human["verified_by"] == ids["officer"]
    assert human["source_span_start"] is None, (
        "a hand-entered value has no span into the OCR text, and inventing one would "
        "make invariant 7's provenance a lie"
    )

    async with engine.connect() as conn:
        machine = (
            await conn.execute(
                sa.text("SELECT value, status, source FROM extracted_field WHERE id = :i"),
                {"i": field["id"]},
            )
        ).mappings().one()
    assert machine["value"] == field["value"]
    assert machine["source"] == "regex"


async def test_manual_entry_needs_no_machine_field_to_exist(api):
    """The manual path is complete, not degraded (CLAUDE.md, reliability invariants).

    Low-confidence OCR extracts nothing at all, so the only way a field reaches the
    record on that path is a human typing it. If this route required a draft to
    correct, that path would dead-end.
    """
    client, ids, _ = api
    await sign_in(client, ids["officer"])
    response = await client.post(
        f"/versions/{ids['version']}/fields",
        json={"field_key": "officer_remark", "value": "Entered from the paper file"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["source"] == "human"


async def test_a_grantee_cannot_enter_a_field_either(api):
    client, ids, _ = api
    await sign_in(client, ids["grantee"])
    response = await client.post(
        f"/versions/{ids['version']}/fields",
        json={"field_key": "officer_remark", "value": "not mine to write"},
    )
    assert response.status_code == 404


# --- 5b+ span highlighting ---------------------------------------------------


async def test_a_field_span_resolves_to_boxes_on_the_page(api):
    """Slice 5b+. The span is char offsets; the scan needs rectangles.

    `ocr_word` carries both, so the mapping is a range query rather than a second
    source of truth. A field whose span matched no words would highlight nothing and
    look like a rendering bug, so the emptiness is asserted against rather than
    tolerated.
    """
    client, ids, _ = api
    await sign_in(client, ids["officer"])
    field = await first_draft_field(client, ids["version"])

    response = await client.get(f"/fields/{field['id']}/spans")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["boxes"], "the field's char span matched no OCR words"
    for box in body["boxes"]:
        assert box["x1"] > box["x0"] and box["y1"] > box["y0"]
    assert body["page_width"] > 0 and body["page_height"] > 0


async def test_spans_are_refused_outside_the_disclosure_class(api):
    """A bounding box is a claim about where a value sits on the original page.

    Handing it to a subject who may not read that page leaks position and length —
    which is the same shape of leak as VIC-01, one level of indirection out.
    """
    client, ids, _ = api
    await sign_in(client, ids["officer"])
    field = await first_draft_field(client, ids["version"])
    await client.delete("/session")

    await sign_in(client, ids["grantee"])
    assert (await client.get(f"/fields/{field['id']}/spans")).status_code == 404


# --- the session cookie is still the only identity ---------------------------


async def test_identity_headers_are_ignored_on_the_new_routes(api):
    """The same assertion `test_api_authorization.py` makes, on this slice's surface.

    Repeated rather than assumed: every new route is a fresh chance to read a header,
    and the failure is invisible — every test above would keep passing.
    """
    client, ids, _ = api
    headers = {
        "X-Role": "supervisor",
        "X-User-Id": ids["officer"],
        "X-Clearance": "3",
        "Authorization": f"Bearer {ids['officer']}",
    }
    assert (
        await client.get(f"/versions/{ids['version']}/fields", headers=headers)
    ).status_code == 401
    assert (
        await client.post(f"/fields/{uuid.uuid4()}/verify", headers=headers)
    ).status_code == 401


async def test_a_forged_session_cookie_is_refused(api):
    client, ids, _ = api
    client.cookies.set(COOKIE_NAME, f"{ids['officer']}.notasignature")
    assert (await client.get(f"/versions/{ids['version']}/fields")).status_code == 401
