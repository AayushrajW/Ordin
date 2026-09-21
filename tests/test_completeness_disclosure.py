"""Completeness is investigative state, and follows disclosure class.

The bug this file was written against: `GET /cases/{id}/completeness` gated on **case
access** and nothing else. A grantee passes that filter — that is what a grant is for —
and would have received a count of every document in the case by class.

That is the VIC-01 shape arriving through a third door. A case holding three FIRs and
one redacted derivative would have told a grantee "fir: 3" while showing them one
document, confirming the existence of two originals whose existence the document routes
deliberately refuse to confirm (threat INS-08).

Disclosure class is stricter than the case filter, and this endpoint is now on the
strict side of it.
"""
import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from api.main import create_app
from infra.tables import app_user

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
        yield client, ids
    await engine.dispose()


async def sign_in(client, user_id: str) -> None:
    assert (await client.post("/session", json={"user_id": user_id})).status_code == 200


async def test_a_designated_officer_sees_the_checklist(api):
    client, ids = api
    await sign_in(client, ids["officer"])
    cases = (await client.get("/cases")).json()
    assert cases, "the officer can reach no case"

    response = await client.get(f"/cases/{cases[0]['id']}/completeness")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "percent" in body and "shortfalls" in body


async def test_a_grantee_is_refused_the_checklist(api):
    """The whole point of this file.

    The grantee can reach the case. They receive redacted derivatives, and a count of
    the case's documents by class would tell them how many originals exist — including
    ones with no derivative, which they are not supposed to be able to confirm at all.
    """
    client, ids = api
    await sign_in(client, ids["grantee"])
    cases = (await client.get("/cases")).json()
    assert cases, "the grantee holds no grant; the test cannot discriminate"

    response = await client.get(f"/cases/{cases[0]['id']}/completeness")
    assert response.status_code == 404, (
        f"a grantee received the completeness report ({response.status_code}). Passing "
        "the case filter is not enough: the counts describe originals they may not read"
    )


async def test_the_refusal_is_the_same_404_as_a_case_that_does_not_exist(api):
    """Denied and nonexistent stay indistinguishable, as everywhere else."""
    client, ids = api
    await sign_in(client, ids["grantee"])
    reachable = (await client.get("/cases")).json()[0]["id"]

    denied = await client.get(f"/cases/{reachable}/completeness")
    missing = await client.get(
        "/cases/00000000-0000-0000-0000-000000000000/completeness"
    )
    assert denied.status_code == missing.status_code == 404
    assert denied.json() == missing.json()
