"""The HTTP surface, tested for what it refuses.

Slice 3a proved the predicate works at the query layer. This proves the routes
actually use it, and — more importantly — that identity cannot be supplied by the
caller.

The single most valuable test in this file is
`test_identity_headers_are_ignored`. Slice 7's demo is "one document, three roles, one
URL", and the cheapest implementation of a role switch is a header or query parameter
the API trusts. If that ever ships, every authorization test in the project keeps
passing while testing a forgeable identity, and Sentinel's unauthorized-access
scenario goes green against an attacker who typed a different value (threat EXT-02).
"""
import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from api.main import create_app
from infra.subject_provider import COOKIE_NAME
from infra.tables import app_user, case_record

pytestmark = pytest.mark.requires_db


@pytest.fixture
async def api(live_settings):
    """A client against the real app, with the real database behind it."""
    import seed as seed_module

    await seed_module.seed()
    app = create_app(live_settings)
    engine = create_async_engine(live_settings.app_dsn)
    app.state.engine = engine

    ids = {}
    async with engine.connect() as conn:
        for fragment, key in (("SI Kavya", "officer"), ("PP Meera", "lapsed"),
                              ("PP Arjun", "grantee")):
            ids[key] = str(
                (
                    await conn.execute(
                        sa.select(app_user.c.id).where(
                            app_user.c.display_name.like(f"{fragment}%")
                        )
                    )
                ).scalar_one()
            )
        ids["sealed_case"] = str(
            (
                await conn.execute(
                    sa.select(case_record.c.id).where(case_record.c.access_class == "sealed")
                )
            ).scalar_one()
        )
        ids["total_cases"] = (
            await conn.execute(sa.select(sa.func.count()).select_from(case_record))
        ).scalar_one()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        yield client, ids
    await engine.dispose()


async def sign_in(client, user_id: str) -> None:
    response = await client.post("/session", json={"user_id": user_id})
    assert response.status_code == 200, response.text


# --- no session, no access ---------------------------------------------------

@pytest.mark.parametrize(
    "path", ["/cases", "/cases/count", "/search?q=VRN", "/parties/suggest?q=An", "/session"]
)
async def test_every_protected_route_refuses_without_a_session(api, path):
    client, _ = api
    assert (await client.get(path)).status_code == 401


async def test_a_forged_cookie_is_refused(api):
    client, ids = api
    client.cookies.set(COOKIE_NAME, "not.a.real.token")
    assert (await client.get("/cases")).status_code == 401


# --- the test this file exists for -------------------------------------------

@pytest.mark.parametrize(
    "headers",
    [
        {"X-Role": "admin"},
        {"X-User-Id": "someone-else"},
        {"X-Clearance": "3"},
        {"Authorization": "Bearer anything"},
    ],
)
async def test_identity_headers_are_ignored(api, headers):
    """Identity comes from the signed cookie and from nothing else.

    Sent with NO session: if any of these were read, the request would succeed.
    """
    client, _ = api
    assert (await client.get("/cases", headers=headers)).status_code == 401


async def test_a_role_query_parameter_does_not_widen_access(api):
    client, ids = api
    await sign_in(client, ids["officer"])
    plain = (await client.get("/cases")).json()
    escalated = (await client.get("/cases?role=admin&clearance=3")).json()
    assert plain == escalated, "a query parameter changed what the caller could see"


# --- the filter is actually applied ------------------------------------------

async def test_list_is_narrower_than_the_whole_table(api):
    client, ids = api
    await sign_in(client, ids["officer"])
    rows = (await client.get("/cases")).json()
    assert 0 < len(rows) < ids["total_cases"]


async def test_count_matches_the_list_and_is_not_the_total(api):
    client, ids = api
    await sign_in(client, ids["officer"])
    listed = len((await client.get("/cases?limit=50")).json())
    counted = (await client.get("/cases/count")).json()["count"]
    assert listed == counted < ids["total_cases"]


async def test_a_lapsed_clearance_sees_nothing_over_http(api):
    client, ids = api
    await sign_in(client, ids["lapsed"])
    assert (await client.get("/cases")).json() == []
    assert (await client.get("/cases/count")).json()["count"] == 0


async def test_a_grantee_sees_only_the_granted_case(api):
    client, ids = api
    await sign_in(client, ids["grantee"])
    assert len((await client.get("/cases")).json()) == 1


# --- 404 rather than 403 -----------------------------------------------------

async def test_an_unauthorized_case_is_indistinguishable_from_a_missing_one(api):
    """A 403 confirms the case exists (threat INS-04)."""
    import uuid

    client, ids = api
    await sign_in(client, ids["officer"])
    denied = await client.get(f"/cases/{ids['sealed_case']}")
    missing = await client.get(f"/cases/{uuid.uuid4()}")
    assert denied.status_code == missing.status_code == 404
    assert denied.json() == missing.json(), (
        f"the two responses differ, which is an existence oracle: "
        f"{denied.json()} vs {missing.json()}"
    )


async def test_an_authorized_case_is_returned(api):
    client, ids = api
    await sign_in(client, ids["officer"])
    listed = (await client.get("/cases")).json()
    fetched = await client.get(f"/cases/{listed[0]['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["reference"] == listed[0]["reference"]


# --- autocomplete -------------------------------------------------------------

async def test_autocomplete_does_not_surface_a_sealed_case_name(api):
    """Three letters must never surface a name from an unauthorised case."""
    client, ids = api
    await sign_in(client, ids["officer"])
    for prefix in ("Sun", "Kal", "unit"):
        names = [s["display_name"] for s in (await client.get(f"/parties/suggest?q={prefix}")).json()]
        assert not any("Sunita" in n for n in names), f"{prefix!r} leaked: {names}"


async def test_autocomplete_returns_authorized_names(api):
    client, ids = api
    await sign_in(client, ids["officer"])
    names = [s["display_name"] for s in (await client.get("/parties/suggest?q=Anj")).json()]
    assert any("Anjali" in n for n in names), f"nothing returned - the test above is vacuous: {names}"


# --- every decision is recorded ----------------------------------------------

async def test_fetching_a_case_writes_a_policy_decision(api, live_settings):
    """Invariant 3, over HTTP rather than in a unit test."""
    client, ids = api
    await sign_in(client, ids["officer"])

    engine = create_async_engine(live_settings.owner_dsn)
    async with engine.connect() as conn:
        before = (
            await conn.execute(sa.text("SELECT count(*) FROM policy_decision"))
        ).scalar_one()

    await client.get(f"/cases/{ids['sealed_case']}")  # a denial

    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT effect, policy_id, rule_id FROM policy_decision "
                    "ORDER BY seq DESC LIMIT 1"
                )
            )
        ).mappings().all()
        after = (
            await conn.execute(sa.text("SELECT count(*) FROM policy_decision"))
        ).scalar_one()
    await engine.dispose()

    assert after == before + 1, "the denial was not recorded"
    assert rows[0]["effect"] == "deny"
    assert rows[0]["policy_id"] == "ordin.case_read"
    assert rows[0]["rule_id"]


# --- session hygiene ----------------------------------------------------------

async def test_the_session_cookie_is_httponly_and_samesite(api):
    """Script cannot read it; a cross-site page cannot drive it (threat SESS-03)."""
    client, ids = api
    response = await client.post("/session", json={"user_id": ids["officer"]})
    header = response.headers.get("set-cookie", "")
    assert "httponly" in header.lower()
    assert "samesite=lax" in header.lower()


async def test_session_endpoint_reports_the_server_view_not_the_callers(api):
    client, ids = api
    await sign_in(client, ids["officer"])
    body = (await client.get("/session", headers={"X-User-Id": "someone-else"})).json()
    assert body["user_id"] == ids["officer"]
    assert body["provider"] == "SimulatedSubjectProvider"
    assert body["maturity"] == "mvp"


async def test_signing_in_as_an_unknown_subject_is_refused(api):
    import uuid

    client, _ = api
    assert (await client.post("/session", json={"user_id": str(uuid.uuid4())})).status_code == 404
