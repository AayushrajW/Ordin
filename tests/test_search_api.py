"""Search (docs/PLAN-PRODUCT.md P4).

Invariant 1 names search as the worst offender, and this file is written against the
two ways it leaks that look like features.

**Result sets.** A term that appears only in a case the caller cannot open must return
nothing — not a redacted row, not a count, not a "1 result you may not view".

**Snippets.** Passing the case filter is not enough to receive *text*. A grantee gets
redacted derivatives, and the original's OCR text is the same content in another shape
(threat VIC-01). A snippet drawn from `ocr_text` would hand them precisely what
redaction destroyed, through a search box — which is the exact shape of the leak the
coverage pass found in slice 7, arriving through a new door.
"""
import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from api.main import create_app
from infra.tables import app_user, case_record

pytestmark = pytest.mark.requires_db


@pytest.fixture
async def api(live_settings):
    import demo as demo_module
    import seed as seed_module

    await seed_module.seed()
    await demo_module.load_demo()

    app = create_app(live_settings)
    engine = create_async_engine(live_settings.app_dsn)
    app.state.engine = engine

    ids = {}
    async with engine.connect() as conn:
        for fragment, key in (("SI Kavya", "officer"), ("PP Arjun", "grantee"),
                              ("PP Meera", "lapsed")):
            ids[key] = str(
                (
                    await conn.execute(
                        sa.select(app_user.c.id).where(
                            app_user.c.display_name.like(f"{fragment}%")
                        )
                    )
                ).scalar_one()
            )
        ids["references"] = [
            r for r in (await conn.execute(sa.select(case_record.c.reference))).scalars().all()
        ]

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        yield client, engine, ids
    await engine.dispose()


async def sign_in(client, user_id: str) -> None:
    assert (await client.post("/session", json={"user_id": user_id})).status_code == 200


async def _a_word_from_an_original(engine) -> str:
    """A word that genuinely appears in an original's OCR text.

    Taken from the data rather than hardcoded: OCR output is not stable enough across
    machines to assert a literal, and a test that searched for a word which happens not
    to be there would pass by finding nothing, proving the opposite of what it claims.
    """
    async with engine.connect() as conn:
        text = (
            await conn.execute(
                sa.text(
                    "SELECT o.text FROM ocr_text o "
                    "JOIN document_version v ON v.id = o.version_id "
                    "WHERE v.derived_from_version_id IS NULL "
                    "AND length(o.text) > 40 LIMIT 1"
                )
            )
        ).scalar_one()
    words = [w.strip(".,:;()[]") for w in text.split()]
    return next(w for w in words if len(w) >= 6 and w.isalpha())


# --- no session, no search -------------------------------------------------------


async def test_search_refuses_without_a_session(api):
    client, _, _ = api
    assert (await client.get("/search/all?q=VRN")).status_code == 401


# --- result sets -----------------------------------------------------------------


async def test_a_reference_from_an_unreachable_case_returns_nothing(api):
    """Not a redacted row, not a count. Nothing."""
    client, engine, ids = api
    await sign_in(client, ids["officer"])

    mine = (await client.get("/search/all?q=VRN")).json()
    my_refs = {c["reference"] for c in mine["cases"]}
    others = [r for r in ids["references"] if r not in my_refs]
    assert others, "the fixture gives this subject every case; the test cannot discriminate"

    for reference in others:
        found = (await client.get(f"/search/all?q={reference}")).json()
        assert found["cases"] == [], (
            f"searching the exact reference of an unreachable case returned "
            f"{found['cases']} — the predicate is not inside the query"
        )
        assert found["documents"] == []


async def test_an_identity_with_no_route_searches_an_empty_world(api):
    client, _, ids = api
    await sign_in(client, ids["lapsed"])
    body = (await client.get("/search/all?q=VRN")).json()
    assert body["cases"] == [] and body["documents"] == []


# --- snippets, and VIC-01 ---------------------------------------------------------


async def test_a_designated_officer_gets_snippets_from_the_original(api):
    client, engine, ids = api
    await sign_in(client, ids["officer"])
    word = await _a_word_from_an_original(engine)

    body = (await client.get(f"/search/all?q={word}")).json()
    assert body["documents"], (
        f"a word taken from an original's own OCR text ({word!r}) matched no document"
    )
    assert any(d["snippet"] for d in body["documents"]), "no snippet was produced"


async def test_a_grantee_gets_no_document_content_at_all(api):
    """The VIC-01 control, arriving through the search box.

    The grantee can reach the case — that is what a grant is for — and must receive no
    text drawn from the original, because redaction destroyed exactly that content in
    the copy they are entitled to.
    """
    client, engine, ids = api
    word = await _a_word_from_an_original(engine)

    await sign_in(client, ids["officer"])
    officer = (await client.get(f"/search/all?q={word}")).json()
    assert officer["documents"], "precondition failed: the officer finds nothing either"

    await client.delete("/session")
    await sign_in(client, ids["grantee"])
    grantee = (await client.get(f"/search/all?q={word}")).json()

    assert grantee["documents"] == [], (
        "a grantee received document text from a search. The original's OCR text is "
        "original content in a different shape (threat VIC-01), and redaction removed "
        "it from the copy they are entitled to"
    )
    assert grantee["content_withheld"] is True
    assert grantee["note"], "the response did not say that content was not searched"


async def test_the_grantee_can_still_find_the_case_itself(api):
    """Withholding content is not withholding the case. They hold a lawful grant."""
    client, _, ids = api
    await sign_in(client, ids["grantee"])
    body = (await client.get("/search/all?q=VRN")).json()
    assert body["cases"], "the grant opened no case to search"


# --- the query is data, never syntax ---------------------------------------------


@pytest.mark.parametrize("hostile", ["a & b", "a | b", "!a", "a <-> b", "'; DROP TABLE--"])
async def test_query_operators_are_treated_as_words(api, hostile):
    """`plainto_tsquery` parses no operators, and the term is always a bound parameter.

    A tsquery built by string concatenation would let a caller write their own boolean
    expression over an index they cannot otherwise reach.
    """
    client, _, ids = api
    await sign_in(client, ids["officer"])
    response = await client.get("/search/all", params={"q": hostile})
    assert response.status_code == 200, response.text
