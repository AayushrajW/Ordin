"""The hardening pass: headers, rate limits, verify-on-read, view audit, new routes.

Each control is tested against the condition it exists to catch, not merely for being
present — the lesson of three controls in this project that looked applied and did
nothing. The tamper test asserts the bytes actually changed before asserting a refusal;
the rate-limit test asserts requests under the limit succeed before asserting the one
over it fails.
"""
import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from api.main import create_app
from api.security import SlidingWindow
from infra.anchor import LocalAnchorStore
from infra.blobstore import LocalBlobStore
from infra.esign import SimulatedESignProvider
from infra.pipeline import Pipeline
from infra.tables import app_user, case_record
from infra.textsource import EmbeddedTextLayer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATEMENT = ROOT / "fixtures" / "corpus" / "statement-0011.pdf"


# --- pure ---------------------------------------------------------------------


def test_the_sliding_window_admits_up_to_the_limit_and_then_refuses():
    window = SlidingWindow(limit=3, seconds=60)
    assert [window.allow("k", now=t)[0] for t in (0, 1, 2)] == [True, True, True]
    allowed, retry = window.allow("k", now=3)
    assert allowed is False and retry >= 1


def test_the_window_forgets_hits_older_than_its_span():
    window = SlidingWindow(limit=1, seconds=10)
    assert window.allow("k", now=0)[0]
    assert not window.allow("k", now=5)[0]
    assert window.allow("k", now=11)[0]


def test_keys_are_independent():
    window = SlidingWindow(limit=1)
    assert window.allow("a", now=0)[0] and window.allow("b", now=0)[0]


# --- against the app ----------------------------------------------------------


@pytest.fixture
async def api(live_settings, tmp_path):
    import seed as seed_module

    await seed_module.seed()
    blobs = LocalBlobStore(tmp_path / "blobs")
    owner = create_async_engine(live_settings.owner_dsn)
    async with owner.connect() as conn:
        case_a = (await conn.execute(
            sa.select(case_record.c.id).where(case_record.c.reference == "VRN-N/2026/0001")
        )).scalar_one()
        actor = (await conn.execute(sa.select(app_user.c.id).limit(1))).scalar_one()
        result = await Pipeline(
            blobs=blobs, text_source=EmbeddedTextLayer(),
            signer=SimulatedESignProvider("t"), anchors=LocalAnchorStore(),
        ).run(conn, case_id=case_a, filename="statement.pdf",
              data=STATEMENT.read_bytes(), actor_id=actor)
        await conn.commit()
    await owner.dispose()

    app = create_app(live_settings)
    engine = create_async_engine(live_settings.app_dsn)
    app.state.engine = engine
    app.state.blobs = blobs
    ids = {"version": result.version_id, "document": result.document_id,
           "sha": result.content_sha256}
    async with engine.connect() as conn:
        for fragment, key in (("SI Kavya", "officer"), ("PP Arjun", "grantee")):
            ids[key] = str((await conn.execute(
                sa.select(app_user.c.id).where(app_user.c.display_name.like(f"{fragment}%"))
            )).scalar_one())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        yield client, ids, engine, blobs
    await engine.dispose()


async def sign_in(client, user_id):
    assert (await client.post("/session", json={"user_id": user_id})).status_code == 200


pytestmark_db = pytest.mark.requires_db


@pytestmark_db
async def test_every_response_carries_the_hardened_headers(api):
    client, ids, _, _ = api
    await sign_in(client, ids["officer"])
    for path in ("/cases", "/health", f"/versions/{ids['version']}/fields"):
        headers = (await client.get(path)).headers
        assert "no-store" in headers["cache-control"], path
        assert headers["x-content-type-options"] == "nosniff", path
        assert headers["x-frame-options"] == "DENY", path
        assert "frame-ancestors 'none'" in headers["content-security-policy"], path


@pytestmark_db
async def test_minting_sessions_is_rate_limited(api):
    """Under the limit succeeds; the request over it is refused with Retry-After."""
    client, ids, _, _ = api
    statuses = [(await client.post("/session", json={"user_id": ids["officer"]})).status_code
                for _ in range(31)]
    assert statuses[:30] == [200] * 30, "requests under the limit were refused"
    assert statuses[30] == 429
    refused = await client.post("/session", json={"user_id": ids["officer"]})
    assert int(refused.headers["retry-after"]) >= 1
    assert refused.headers["x-content-type-options"] == "nosniff", "a refusal lost its headers"


@pytestmark_db
async def test_a_tampered_document_is_refused_on_read(api):
    client, ids, _, blobs = api
    await sign_in(client, ids["officer"])
    assert (await client.get(f"/versions/{ids['version']}/page.png")).status_code == 200

    path = blobs._path(ids["sha"])
    original = path.read_bytes()
    altered = bytearray(original)
    altered[len(altered) // 2] ^= 0x01
    assert bytes(altered) != original, "the tamper changed nothing, so this would prove nothing"
    path.write_bytes(bytes(altered))
    try:
        page = await client.get(f"/versions/{ids['version']}/page.png")
        verdict = (await client.get(f"/versions/{ids['version']}/integrity")).json()
    finally:
        path.write_bytes(original)
    assert page.status_code == 409 and page.json()["detail"] == "integrity_mismatch"
    assert verdict["state"] == "MISMATCH"


@pytestmark_db
async def test_an_intact_document_verifies(api):
    client, ids, _, _ = api
    await sign_in(client, ids["officer"])
    verdict = (await client.get(f"/versions/{ids['version']}/integrity")).json()
    assert verdict["state"] == "VERIFIED"
    assert verdict["anchor_seq"] is not None


@pytestmark_db
async def test_every_page_view_appends_an_audit_row(api):
    client, ids, engine, _ = api
    await sign_in(client, ids["officer"])
    async with engine.connect() as conn:
        before = (await conn.execute(sa.text(
            "SELECT count(*) FROM audit_event WHERE action='document_viewed' AND object_id=:v"
        ), {"v": ids["version"]})).scalar_one()
    for _ in range(2):
        assert (await client.get(f"/versions/{ids['version']}/page.png")).status_code == 200
    async with engine.connect() as conn:
        after = (await conn.execute(sa.text(
            "SELECT count(*) FROM audit_event WHERE action='document_viewed' AND object_id=:v"
        ), {"v": ids["version"]})).scalar_one()
    assert after == before + 2


@pytestmark_db
async def test_the_rendered_page_differs_per_viewer(api):
    """The watermark is burned in, so two viewers receive different pixels."""
    client, ids, engine, _ = api
    await sign_in(client, ids["officer"])
    first = (await client.get(f"/versions/{ids['version']}/page.png")).content
    async with engine.begin() as conn:
        # A second designated officer, so the only difference is who is looking.
        rahul = (await conn.execute(sa.text(
            "SELECT id FROM app_user WHERE display_name LIKE 'SHO Rahul%'"))).scalar_one()
    await client.delete("/session")
    await sign_in(client, str(rahul))
    second = (await client.get(f"/versions/{ids['version']}/page.png")).content
    assert first[:8] == second[:8] == b"\x89PNG\r\n\x1a\n"
    assert first != second, "two viewers received identical pixels: no watermark"


@pytestmark_db
async def test_the_redaction_plan_finds_the_narrative_mentions(api):
    client, ids, _, _ = api
    await sign_in(client, ids["officer"])
    plan = (await client.get(f"/versions/{ids['version']}/redaction-plan")).json()
    narrative = [f for f in plan["findings"] if not f["labelled"]]
    assert narrative, "only labelled lines were found; the narrative mentions survive"
    assert all(f["boxes"] for f in plan["findings"])
    assert not any("Rukmini" in str(f) or "Deshmukh" in str(f) for f in plan["findings"]), (
        "the plan carried identifying text back out"
    )


@pytestmark_db
async def test_a_grantee_gets_no_plan_and_no_activity(api):
    client, ids, _, _ = api
    await sign_in(client, ids["grantee"])
    assert (await client.get(f"/versions/{ids['version']}/redaction-plan")).status_code == 404
    assert (await client.get(f"/documents/{ids['document']}/activity")).json() == []


@pytestmark_db
async def test_fields_carry_ocr_confidence_and_anomalies(api):
    client, ids, _, _ = api
    await sign_in(client, ids["officer"])
    fields = (await client.get(f"/versions/{ids['version']}/fields")).json()
    assert fields and all("anomalies" in f and "ocr_confidence" in f for f in fields)
