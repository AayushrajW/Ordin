"""Export and disposal: two verbs the audit vocabulary named and nothing could write.

`AuditAction.DOCUMENT_EXPORTED` and `AuditAction.DISPOSAL_RECORDED` existed from slice
2 with no caller, which made two claims hollow at once. Export was not a verb, so
reading a document and taking a copy of it were the same event to the system - the
difference between an officer working a case and an officer emptying it was invisible
(threat AR-17). And `DISPOSED_ANCHOR_ONLY`, one of the five states security invariant 5
is built on, was unreachable: an integrity model with a dead branch in the place that
matters most.

The claims under test:

  export     byte-exact, refused when the document does not verify, counted in
             `export_record`, and scoped by disclosure so a grantee exports
             derivatives only
  disposal   destroys the stored bytes *and the derived text*, keeps the anchor and
             the disposition record, refuses to run on an unanchored version, and
             leaves `verify()` returning DISPOSED_ANCHOR_ONLY rather than MISMATCH

The sharpest test here is `test_disposal_does_not_destroy_a_shared_address`. The blob
store is content-addressed, so one file can back several versions; disposing one of
them must not silently destroy the others. The store cannot see the case record, so
the check has to be on this side, and nothing would have failed loudly if it were
missing - the second version would simply have started verifying as MISMATCH one day.
"""
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from api.main import create_app
from infra.anchor import LocalAnchorStore
from infra.blobstore import LocalBlobStore
from infra.esign import SimulatedESignProvider
from infra.pipeline import Pipeline
from infra.tables import app_user, case_record
from infra.textsource import EmbeddedTextLayer

pytestmark = pytest.mark.requires_db

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "corpus" / "complaint-0001.pdf"


@pytest.fixture
async def api(live_settings, tmp_path):
    import seed as seed_module

    await seed_module.seed()

    owner = create_async_engine(live_settings.owner_dsn)
    blob_root = tmp_path / "blobs"
    store = LocalBlobStore(blob_root)
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
        result = await Pipeline(
            blobs=store,
            text_source=EmbeddedTextLayer(),
            signer=SimulatedESignProvider("test-secret"),
            anchors=LocalAnchorStore(),
        ).run(
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
    app.state.blobs = LocalBlobStore(blob_root)

    ids = {
        "case": str(case_a),
        "version": result.version_id,
        "document": result.document_id,
        "sha256": result.content_sha256,
    }
    async with engine.connect() as conn:
        for fragment, key in (("SI Kavya", "officer"), ("PP Arjun", "grantee")):
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
        yield client, ids, engine, LocalBlobStore(blob_root)
    await engine.dispose()


async def sign_in(client, user_id: str) -> None:
    assert (await client.post("/session", json={"user_id": user_id})).status_code == 200


def blob_path(store: LocalBlobStore, address: str) -> Path:
    return store.root / address[:2] / address[2:4] / address


# --- export ---------------------------------------------------------------------


async def test_a_session_is_required_to_export(api):
    client, ids, _, _ = api
    assert (await client.get(f"/versions/{ids['version']}/export")).status_code == 401
    assert (await client.get(f"/cases/{ids['case']}/export")).status_code == 401


async def test_exporting_one_document_returns_the_exact_stored_bytes(api):
    """Byte-exact, and the digest travels with it.

    The page renderer watermarks; this does not, on purpose. A watermark changes the
    bytes, and changed bytes do not hash to the anchored digest - which destroys the
    one property that makes an export evidential. The recipient must be able to run
    sha256 on what they were handed and have it match the case record.
    """
    import hashlib

    client, ids, _, _ = api
    await sign_in(client, ids["officer"])

    response = await client.get(f"/versions/{ids['version']}/export")
    assert response.status_code == 200, response.text
    assert response.headers["x-ordin-sha256"] == ids["sha256"]
    assert hashlib.sha256(response.content).hexdigest() == ids["sha256"], (
        "the exported bytes do not hash to the anchored digest, so the recipient "
        "cannot verify the copy against the case record"
    )
    assert "attachment" in response.headers["content-disposition"]


async def test_an_export_is_counted(api):
    """AR-17's mitigation: a distinct verb recording row count and disclosure."""
    client, ids, engine, _ = api
    await sign_in(client, ids["officer"])
    assert (await client.get(f"/versions/{ids['version']}/export")).status_code == 200

    async with engine.connect() as conn:
        record = (
            await conn.execute(
                sa.text("SELECT * FROM export_record ORDER BY exported_at DESC LIMIT 1")
            )
        ).mappings().one()
        audit = (
            await conn.execute(
                sa.text(
                    "SELECT action, object_type, object_id FROM audit_event "
                    "ORDER BY seq DESC LIMIT 1"
                )
            )
        ).mappings().one()

    assert record["scope"] == "version"
    assert record["disclosure"] == "original"
    assert record["row_count"] == 1
    assert record["byte_count"] > 0
    assert str(record["actor_id"]) == ids["officer"]
    assert audit["action"] == "document_exported"
    assert audit["object_id"] == ids["version"]


async def test_the_export_record_carries_no_free_text(api):
    """Enumerated columns and counts only (invariant 12).

    AR-17's wording invites a `filter` text column. A free-text field on a record like
    this is where a case reference, a party name or a search term eventually lands,
    written by somebody being helpful.
    """
    client, ids, engine, _ = api
    await sign_in(client, ids["officer"])
    await client.get(f"/versions/{ids['version']}/export")

    async with engine.connect() as conn:
        columns = {
            r["column_name"]: r["data_type"]
            for r in (
                await conn.execute(
                    sa.text(
                        "SELECT column_name, data_type FROM information_schema.columns "
                        "WHERE table_name = 'export_record'"
                    )
                )
            ).mappings()
        }
    free_text = {
        name for name, kind in columns.items()
        if kind == "text" and name not in {"scope", "disclosure"}
    }
    assert not free_text, f"export_record has free-text columns: {sorted(free_text)}"


async def test_a_case_export_bundles_what_the_subject_may_receive(api):
    import io
    import json
    import zipfile

    client, ids, _, _ = api
    await sign_in(client, ids["officer"])

    response = await client.get(f"/cases/{ids['case']}/export")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
        assert len(names) == len(manifest["entries"]) + 1, (
            "the archive holds a different number of files than the manifest lists"
        )
        for entry in manifest["entries"]:
            if entry["included"]:
                assert entry["integrity"] == "VERIFIED"

    assert manifest["disclosure"] == "original"
    assert manifest["included"] >= 1


async def test_a_grantee_exports_derivatives_only(api):
    """VIC-01, at the export boundary.

    A purpose-limited grantee receives the redacted derivative in the viewer. If the
    export route resolved versions differently it would hand them the original, and
    every control upstream would have been decorative. It uses `readable_version_ids`,
    the same function the viewer uses, so there is no second code path to disagree.
    """
    client, ids, _, _ = api
    await sign_in(client, ids["grantee"])

    # No derivative exists for this document, so the grantee may receive nothing -
    # and the original must not appear in its place.
    refused = await client.get(f"/versions/{ids['version']}/export")
    assert refused.status_code == 404, refused.text

    bundle = await client.get(f"/cases/{ids['case']}/export")
    assert bundle.status_code == 409
    assert bundle.json()["detail"] == "nothing_to_export"


async def test_a_tampered_document_is_never_exported(api):
    """Sentinel INTEG-01's rule, applied to the strongest form of handing it over."""
    client, ids, _, store = api
    await sign_in(client, ids["officer"])

    path = blob_path(store, ids["sha256"])
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 0x01
    path.write_bytes(bytes(raw))

    refused = await client.get(f"/versions/{ids['version']}/export")
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"].startswith("not_exportable:")


async def test_a_case_export_lists_a_tampered_document_without_enclosing_it(api):
    """Counted, not hidden.

    An export that silently dropped a mismatched document would be the quietest
    possible way to lose a tamper alert: the recipient gets a slightly shorter case
    file and nobody ever knows.
    """
    import io
    import json
    import zipfile

    client, ids, engine, store = api
    await sign_in(client, ids["officer"])

    path = blob_path(store, ids["sha256"])
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 0x01
    path.write_bytes(bytes(raw))

    response = await client.get(f"/cases/{ids['case']}/export")
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["excluded"] >= 1
    excluded = [e for e in manifest["entries"] if not e["included"]]
    assert excluded and excluded[0]["integrity"] == "MISMATCH"

    async with engine.connect() as conn:
        record = (
            await conn.execute(
                sa.text("SELECT * FROM export_record ORDER BY exported_at DESC LIMIT 1")
            )
        ).mappings().one()
    assert record["excluded_count"] >= 1


# --- disposal -------------------------------------------------------------------


async def test_disposal_reaches_the_bytes_the_text_and_the_index(api):
    """AR-13's first half, closed as far as this system reaches.

    A disposal that left the OCR of a destroyed document sitting in `ocr_text` -
    searchable - would be a disposal in name only.
    """
    client, ids, engine, store = api
    await sign_in(client, ids["officer"])

    async with engine.connect() as conn:
        before = (
            await conn.execute(
                sa.text("SELECT count(*) FROM ocr_text WHERE version_id = :v"),
                {"v": ids["version"]},
            )
        ).scalar_one()
    assert before == 1, "no OCR text to dispose of, so this test proves nothing"
    assert blob_path(store, ids["sha256"]).exists()

    disposed = await client.post(
        f"/versions/{ids['version']}/dispose", json={"basis": "retention_expiry"}
    )
    assert disposed.status_code == 200, disposed.text
    assert disposed.json()["bytes_destroyed"] is True

    assert not blob_path(store, ids["sha256"]).exists()
    async with engine.connect() as conn:
        for table in ("ocr_text", "ocr_word", "extracted_field"):
            remaining = (
                await conn.execute(
                    sa.text(f"SELECT count(*) FROM {table} WHERE version_id = :v"),
                    {"v": ids["version"]},
                )
            ).scalar_one()
            assert remaining == 0, f"{table} survived the disposal"


async def test_a_disposed_version_verifies_as_disposed_not_as_tampered(api):
    """Security invariant 5, and the whole reason it is a state and not a boolean.

    Reporting MISMATCH for a lawfully destroyed document is not a cosmetic bug. It is
    a claim that evidence was tampered with.
    """
    client, ids, _, _ = api
    await sign_in(client, ids["officer"])
    assert (
        await client.post(
            f"/versions/{ids['version']}/dispose", json={"basis": "court_order"}
        )
    ).status_code == 200

    verdict = await client.get(f"/versions/{ids['version']}/integrity")
    assert verdict.status_code == 200
    assert verdict.json()["state"] == "DISPOSED_ANCHOR_ONLY", verdict.json()


async def test_disposal_is_recorded_with_its_basis_and_on_the_chain(api):
    client, ids, engine, _ = api
    await sign_in(client, ids["officer"])
    await client.post(
        f"/versions/{ids['version']}/dispose", json={"basis": "erroneous_upload"}
    )

    async with engine.connect() as conn:
        record = (
            await conn.execute(
                sa.text("SELECT * FROM disposition WHERE version_id = :v"),
                {"v": ids["version"]},
            )
        ).mappings().one()
        audit = (
            await conn.execute(
                sa.text(
                    "SELECT action, object_type, object_id FROM audit_event "
                    "ORDER BY seq DESC LIMIT 1"
                )
            )
        ).mappings().one()

    assert record["basis"] == "erroneous_upload"
    assert str(record["disposed_by"]) == ids["officer"]
    assert audit["action"] == "disposal_recorded"
    assert audit["object_id"] == ids["version"]


async def test_an_unknown_basis_is_refused(api):
    """The CHECK constraint is in the database; this is the 422 at the edge."""
    client, ids, _, _ = api
    await sign_in(client, ids["officer"])
    refused = await client.post(
        f"/versions/{ids['version']}/dispose", json={"basis": "because-i-said-so"}
    )
    assert refused.status_code == 422


async def test_a_second_disposal_is_refused(api):
    """Not idempotent-and-silent: a second disposal is not a second lawful act, and
    writing a second chain row for something that did not happen is worse than a 409.
    """
    client, ids, _, _ = api
    await sign_in(client, ids["officer"])
    assert (
        await client.post(
            f"/versions/{ids['version']}/dispose", json={"basis": "retention_expiry"}
        )
    ).status_code == 200
    again = await client.post(
        f"/versions/{ids['version']}/dispose", json={"basis": "retention_expiry"}
    )
    assert again.status_code == 409
    assert again.json()["detail"] == "already_disposed"


async def test_an_unanchored_version_cannot_be_disposed(api, live_settings):
    """Destroying bytes you were never able to attest to leaves an absence nobody
    can explain - UNAVAILABLE for ever, which is not what lawful disposal looks like.

    The anchor is removed through the **owner** role, because the app role has no
    DELETE on `anchor_record` and must not - that is invariant 10 working. Setting the
    precondition for this test requires privileges the application itself never holds,
    which is a small proof of the same thing.
    """
    client, ids, _, _ = api
    owner = create_async_engine(live_settings.owner_dsn)
    async with owner.begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM anchor_record WHERE version_id = :v"),
            {"v": ids["version"]},
        )
    await owner.dispose()
    await sign_in(client, ids["officer"])
    refused = await client.post(
        f"/versions/{ids['version']}/dispose", json={"basis": "retention_expiry"}
    )
    assert refused.status_code == 409
    assert refused.json()["detail"] == "not_anchored"


async def test_disposal_does_not_destroy_a_shared_address(api):
    """The subtle one, and the one nothing would have failed loudly about.

    The store is content-addressed, so the same bytes filed into two cases are one
    file. Deleting it on behalf of one version destroys the other - and the store
    cannot see the case record, so it cannot know. The second version would simply
    have started verifying as MISMATCH one day, with no event to point at.
    """
    client, ids, engine, store = api
    # A second version, in another document, backed by the same address.
    async with engine.begin() as conn:
        other_document = str(uuid.uuid4())
        await conn.execute(
            sa.text(
                "INSERT INTO document (id, case_id, title, doc_class) "
                "VALUES (:i, :c, 'duplicate-of-complaint', 'other')"
            ),
            {"i": other_document, "c": ids["case"]},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO document_version "
                "(id, document_id, version_no, sha256, source_sha256, lifecycle_state) "
                "SELECT :i, :d, 1, sha256, source_sha256, 'active' "
                "FROM document_version WHERE id = :v"
            ),
            {"i": str(uuid.uuid4()), "d": other_document, "v": ids["version"]},
        )

    await sign_in(client, ids["officer"])
    disposed = await client.post(
        f"/versions/{ids['version']}/dispose", json={"basis": "superseded_original"}
    )
    assert disposed.status_code == 200, disposed.text
    body = disposed.json()
    assert body["bytes_destroyed"] is False
    assert body["shared_address_retained"] is True
    assert blob_path(store, ids["sha256"]).exists(), (
        "disposing one version destroyed the bytes another version still relies on"
    )


async def test_a_grantee_cannot_dispose(api):
    """Destroying a document you may only see redacted is not a thing to allow."""
    client, ids, _, _ = api
    await sign_in(client, ids["grantee"])
    refused = await client.post(
        f"/versions/{ids['version']}/dispose", json={"basis": "retention_expiry"}
    )
    assert refused.status_code == 404


async def test_a_disposed_version_cannot_be_exported(api):
    client, ids, _, _ = api
    await sign_in(client, ids["officer"])
    await client.post(
        f"/versions/{ids['version']}/dispose", json={"basis": "retention_expiry"}
    )
    refused = await client.get(f"/versions/{ids['version']}/export")
    assert refused.status_code == 409
    assert refused.json()["detail"] == "not_exportable:DISPOSED_ANCHOR_ONLY"


async def test_re_uploading_a_disposed_document_files_a_new_version(api, live_settings):
    """The bug was silence, not the bytes coming back.

    `_upsert_version` called `blobs.put(data)` before looking for an existing version.
    The content address is a digest of the plaintext, so re-uploading a lawfully
    disposed document wrote its bytes back to the very address disposal had unlinked -
    and then MATCHED THE DISPOSED ROW and returned it. No new version, no new audit
    entry, nothing to read: the disposition record was still the only record of that
    document while its bytes sat in the store. And nothing could have caught it from
    outside, because `verify_version` checks disposal before the bytes (invariant 5, and
    correctly), so the verdict never looks at the file.

    Re-filing a document disposed in error is legitimate, so it is not refused. What it
    must do is leave a trace. It now creates a **new version**, append-only, with its own
    anchor and its own audit row - and the disposed version stays disposed. The bytes
    being present afterwards is then a fact about the new version, explained by a record,
    rather than a contradiction of the old one.
    """
    from infra.anchor import LocalAnchorStore
    from infra.esign import SimulatedESignProvider
    from infra.pipeline import Pipeline
    from infra.textsource import EmbeddedTextLayer

    client, ids, engine, store = api
    await sign_in(client, ids["officer"])
    assert (
        await client.post(
            f"/versions/{ids['version']}/dispose", json={"basis": "court_order"}
        )
    ).status_code == 200
    assert not blob_path(store, ids["sha256"]).exists()

    async with engine.connect() as conn:
        before = (
            await conn.execute(
                sa.text(
                    "SELECT count(*) FROM document_version WHERE document_id = :d"
                ),
                {"d": ids["document"]},
            )
        ).scalar_one()

    owner = create_async_engine(live_settings.owner_dsn)
    async with owner.begin() as conn:
        actor = (
            await conn.execute(
                sa.select(app_user.c.id).where(app_user.c.display_name.like("SHO Rahul%"))
            )
        ).scalar_one()
        again = await Pipeline(
            blobs=store,
            text_source=EmbeddedTextLayer(),
            signer=SimulatedESignProvider("test-secret"),
            anchors=LocalAnchorStore(),
        ).run(
            conn,
            case_id=ids["case"],
            filename="complaint-0001.pdf",
            data=FIXTURE.read_bytes(),
            actor_id=actor,
        )
    await owner.dispose()

    assert again.version_id != ids["version"], (
        "the re-upload was absorbed into the DISPOSED version: no new row, no new "
        "audit entry, and the disposition record is still the only account of a "
        "document whose bytes are back on disk"
    )

    async with engine.connect() as conn:
        after = (
            await conn.execute(
                sa.text(
                    "SELECT count(*) FROM document_version WHERE document_id = :d"
                ),
                {"d": ids["document"]},
            )
        ).scalar_one()
        state = (
            await conn.execute(
                sa.text("SELECT lifecycle_state FROM document_version WHERE id = :v"),
                {"v": ids["version"]},
            )
        ).scalar_one()
    assert after == before + 1, "re-filing did not append a version"
    assert state == "disposed", "the disposal was undone rather than superseded"

    verdict = (await client.get(f"/versions/{ids['version']}/integrity")).json()
    assert verdict["state"] == "DISPOSED_ANCHOR_ONLY", verdict


async def test_the_export_routes_are_rate_limited(api):
    """AR-17's other half: export is a GET, so it fell through every bucket.

    The most expensive route in the application - and the one the bulk-exfiltration
    threat is written about - was the only unmetered one.
    """
    from api.security import SecurityMiddleware

    middleware = SecurityMiddleware.__new__(SecurityMiddleware)
    SecurityMiddleware.__init__(middleware, app=None)

    class _Req:
        def __init__(self, path):
            self.url = type("U", (), {"path": path})()
            self.method = "GET"
            self.cookies = {"ordin_session": "t"}
            self.client = type("C", (), {"host": "203.0.113.9"})()

    assert middleware._bucket(_Req("/versions/x/export")) is not None
    assert middleware._bucket(_Req("/cases/x/export")) is not None
    # And it is its own bucket, not the render one - an export must not be able to
    # exhaust the page renders, or the reverse.
    window, _ = middleware._bucket(_Req("/cases/x/export"))
    assert window is middleware.exports


# --- page count -------------------------------------------------------------------


async def test_the_viewer_can_learn_how_many_pages_a_version_has(api):
    """The fact the document page had no way to obtain.

    The scan was rendered at the selected field's page number, defaulting to zero, with
    no navigation - so a long document showed its first page and nothing indicated the
    rest existed. MAX_PAGES is 200, so that is up to 199 pages of evidence present in
    the system and unreachable through the product.
    """
    client, ids, _, _ = api
    await sign_in(client, ids["officer"])

    response = await client.get(f"/versions/{ids['version']}/pages")
    assert response.status_code == 200, response.text
    assert response.json()["page_count"] >= 1


async def test_the_page_count_is_gated_like_the_page_itself(api):
    """Length is a property of the document, so it follows the same disclosure rule.

    A grantee who may not name the original version may not learn how long it is either
    - otherwise the count becomes a small oracle about a document the routes deliberately
    refuse to confirm (threat INS-08).
    """
    client, ids, _, _ = api
    await sign_in(client, ids["grantee"])
    assert (await client.get(f"/versions/{ids['version']}/pages")).status_code == 404


async def test_a_session_is_required_for_the_page_count(api):
    client, ids, _, _ = api
    assert (await client.get(f"/versions/{ids['version']}/pages")).status_code == 401


async def test_a_disposed_version_reports_no_pages_rather_than_failing(api):
    """Zero, with a reason. A disposed document has no bytes by design, so counting
    them is not an error condition and must not surface as one."""
    client, ids, _, _ = api
    await sign_in(client, ids["officer"])
    await client.post(
        f"/versions/{ids['version']}/dispose", json={"basis": "retention_expiry"}
    )
    response = await client.get(f"/versions/{ids['version']}/pages")
    assert response.status_code == 200, response.text
    assert response.json() == {"page_count": 0, "reason": "disposed"}


async def test_counting_pages_writes_no_audit_row(api):
    """`page.png` logs document_viewed because seeing an original is itself evidence.
    Asking how long it is shows nobody anything, and a chain row for it would be noise
    on the one table that must stay worth reading."""
    client, ids, engine, _ = api
    await sign_in(client, ids["officer"])

    async with engine.connect() as conn:
        before = (
            await conn.execute(sa.text("SELECT count(*) FROM audit_event"))
        ).scalar_one()
    assert (await client.get(f"/versions/{ids['version']}/pages")).status_code == 200
    async with engine.connect() as conn:
        after = (
            await conn.execute(sa.text("SELECT count(*) FROM audit_event"))
        ).scalar_one()
    assert after == before
