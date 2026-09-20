"""Case creation and state transitions over HTTP (FIX-4).

`domain/case.py` had a tested state machine and no caller. `tests/test_case_state_machine.py`
proves the transitions are correct in isolation; this proves the application actually
uses them, which is the part that was missing.

Two claims here are security claims rather than feature claims:

**Organization and jurisdiction are not parameters.** They come from the post the server
resolved. Accepting them from the request body would let anyone who may create a case
create one in somebody else's station — the organization dimension defeated at the
moment of creation, before any read filter gets a chance to matter.

**An unreachable case answers 404, not 403, even for a transition.** A 409 "you cannot
move a case from filed to registered" on a case you cannot read would confirm both that
it exists and what state it is in.
"""
import uuid

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from api.main import create_app
from domain.enums import CaseState
from infra.tables import app_user, case_record

pytestmark = pytest.mark.requires_db


def _reference() -> str:
    return f"TST-{uuid.uuid4().hex[:8].upper()}"


@pytest.fixture
async def api(live_settings):
    import seed as seed_module

    await seed_module.seed()
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
        yield client, engine, ids
    await engine.dispose()


async def sign_in(client, user_id: str) -> None:
    assert (await client.post("/session", json={"user_id": user_id})).status_code == 200


# --- creating -------------------------------------------------------------------


async def test_creating_a_case_designates_the_creator_and_opens_it(api):
    """A case nobody can open is not safer, it is lost."""
    client, _, ids = api
    await sign_in(client, ids["officer"])

    before = len((await client.get("/cases")).json())
    created = await client.post("/cases", json={"reference": _reference()})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["state"] == CaseState.REGISTERED.value
    assert body["designated"] is True

    after = (await client.get("/cases")).json()
    assert len(after) == before + 1
    assert any(c["id"] == body["case_id"] for c in after), (
        "the creator cannot see the case they just created"
    )


async def test_the_case_lands_in_the_creators_own_station(api):
    """Organization and jurisdiction come from the post, never from the request."""
    client, engine, ids = api
    await sign_in(client, ids["officer"])
    created = (await client.post("/cases", json={"reference": _reference()})).json()

    async with engine.connect() as conn:
        row = (
            await conn.execute(
                sa.select(
                    case_record.c.organization_id, case_record.c.jurisdiction_id
                ).where(case_record.c.id == created["case_id"])
            )
        ).mappings().one()
        subject_post = (
            await conn.execute(
                sa.text(
                    "SELECT p.organization_id, p.jurisdiction_id FROM app_user u "
                    "JOIN post p ON p.id = u.post_id WHERE u.id = :u"
                ),
                {"u": ids["officer"]},
            )
        ).mappings().one()

    assert str(row["organization_id"]) == str(subject_post["organization_id"])
    assert str(row["jurisdiction_id"]) == str(subject_post["jurisdiction_id"])


async def test_a_body_cannot_choose_someone_elses_organization(api):
    """The fields are not in the model at all, so a caller cannot smuggle them in.

    Pydantic ignores unknown keys here rather than erroring, which is exactly why this
    is worth asserting: a silent ignore looks identical to a silent accept from outside.
    """
    client, engine, ids = api
    await sign_in(client, ids["officer"])

    async with engine.connect() as conn:
        other_org = (
            await conn.execute(
                sa.text(
                    "SELECT id FROM organization WHERE id <> "
                    "(SELECT p.organization_id FROM app_user u JOIN post p ON p.id = u.post_id "
                    " WHERE u.id = :u) LIMIT 1"
                ),
                {"u": ids["officer"]},
            )
        ).scalar_one()

    created = await client.post(
        "/cases",
        json={"reference": _reference(), "organization_id": str(other_org)},
    )
    assert created.status_code == 201
    async with engine.connect() as conn:
        landed = (
            await conn.execute(
                sa.select(case_record.c.organization_id).where(
                    case_record.c.id == created.json()["case_id"]
                )
            )
        ).scalar_one()
    assert str(landed) != str(other_org), (
        "a request body chose the case's organization; the dimension is defeated at "
        "creation, before any read filter can matter"
    )


async def test_a_duplicate_reference_is_refused(api):
    client, _, ids = api
    await sign_in(client, ids["officer"])
    reference = _reference()
    assert (await client.post("/cases", json={"reference": reference})).status_code == 201
    again = await client.post("/cases", json={"reference": reference})
    assert again.status_code == 409


async def test_creation_requires_a_session(api):
    client, _, _ = api
    assert (await client.post("/cases", json={"reference": _reference()})).status_code == 401


async def test_creation_writes_a_case_created_audit_row(api):
    """A declared audit action with no writer reads as a control that exists."""
    client, engine, ids = api
    await sign_in(client, ids["officer"])
    created = (await client.post("/cases", json={"reference": _reference()})).json()

    async with engine.connect() as conn:
        actions = (
            await conn.execute(
                sa.text("SELECT action FROM audit_event WHERE case_id = :c"),
                {"c": created["case_id"]},
            )
        ).scalars().all()
    assert "case_created" in actions, actions


# --- moving ---------------------------------------------------------------------


async def test_a_case_moves_along_its_lifecycle(api):
    client, _, ids = api
    await sign_in(client, ids["officer"])
    case_id = (await client.post("/cases", json={"reference": _reference()})).json()["case_id"]

    moved = await client.post(
        f"/cases/{case_id}/state", json={"state": CaseState.UNDER_INVESTIGATION.value}
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["to"] == CaseState.UNDER_INVESTIGATION.value


async def test_an_illegal_move_is_refused_with_409(api):
    """registered -> in_trial skips two stages and is not in ALLOWED_TRANSITIONS."""
    client, _, ids = api
    await sign_in(client, ids["officer"])
    case_id = (await client.post("/cases", json={"reference": _reference()})).json()["case_id"]

    refused = await client.post(
        f"/cases/{case_id}/state", json={"state": CaseState.IN_TRIAL.value}
    )
    assert refused.status_code == 409, refused.text


async def test_a_closed_case_cannot_be_reopened(api):
    client, _, ids = api
    await sign_in(client, ids["officer"])
    case_id = (await client.post("/cases", json={"reference": _reference()})).json()["case_id"]

    assert (
        await client.post(f"/cases/{case_id}/state", json={"state": CaseState.CLOSED.value})
    ).status_code == 200
    reopened = await client.post(
        f"/cases/{case_id}/state", json={"state": CaseState.UNDER_INVESTIGATION.value}
    )
    assert reopened.status_code == 409, "a closed case was reopened"


async def test_a_case_you_cannot_reach_answers_404_not_409(api):
    """Even for a transition. A 409 would confirm the case exists and its state."""
    client, _, ids = api
    await sign_in(client, ids["officer"])
    case_id = (await client.post("/cases", json={"reference": _reference()})).json()["case_id"]

    await client.delete("/session")
    await sign_in(client, ids["grantee"])
    response = await client.post(
        f"/cases/{case_id}/state", json={"state": CaseState.CLOSED.value}
    )
    assert response.status_code == 404, (
        f"answered {response.status_code} to somebody who cannot read the case; "
        "anything but 404 confirms it exists"
    )


async def test_an_unknown_state_is_refused(api):
    client, _, ids = api
    await sign_in(client, ids["officer"])
    case_id = (await client.post("/cases", json={"reference": _reference()})).json()["case_id"]
    response = await client.post(f"/cases/{case_id}/state", json={"state": "acquitted"})
    assert response.status_code in (409, 422)


async def test_a_transition_writes_an_audit_row(api):
    client, engine, ids = api
    await sign_in(client, ids["officer"])
    case_id = (await client.post("/cases", json={"reference": _reference()})).json()["case_id"]
    await client.post(
        f"/cases/{case_id}/state", json={"state": CaseState.UNDER_INVESTIGATION.value}
    )

    async with engine.connect() as conn:
        actions = (
            await conn.execute(
                sa.text("SELECT action FROM audit_event WHERE case_id = :c"),
                {"c": case_id},
            )
        ).scalars().all()
    assert "case_state_changed" in actions, actions
