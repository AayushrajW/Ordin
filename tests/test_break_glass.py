"""Break-glass on a sealed case: exceptional access that pays for itself in evidence.

CLAUDE.md: "Sealed records require authorization beyond ordinary clearance." That is a
deny, and a deny with no exception is a design that gets worked around - the officer
who needs the file at 2am rings somebody with clearance and borrows their session, and
the system records nothing at all. Break-glass exists so that the exception leaves a
better trail than the workaround does, not so the seal is weaker.

Four claims are tested here, and the third is the one that matters:

  1. A designated officer without sealed clearance is denied. (The seal is real.)
  2. After declaring a written justification, the same officer is admitted, for a
     bounded window.
  3. **Break-glass is not a master key.** A declaration on a case you are not
     designated on admits you to nothing. It removes the seal from the path; it is
     never itself a ground for access.
  4. The justification is written to a table, never to the ledger. Invariant 4 fixes
     what an audit row may carry, and a free-text field on the chain is where a case
     summary eventually lands.
"""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from api.main import create_app
from infra.tables import app_user, case_record

pytestmark = pytest.mark.requires_db

JUSTIFICATION = (
    "Duty officer request: the sealed file is needed to answer a bail objection "
    "listed for hearing this morning and no cleared officer is on station."
)


@pytest.fixture
async def api(live_settings):
    import seed as seed_module

    await seed_module.seed()
    app = create_app(live_settings)
    engine = create_async_engine(live_settings.app_dsn)
    app.state.engine = engine

    ids = {}
    async with engine.connect() as conn:
        for fragment, key in (
            ("SI Kavya", "officer"),      # clearance 1 - ordinary
            ("SHO Rahul", "cleared"),     # clearance 3 - permits sealed
            ("PP Arjun", "grantee"),      # other organization, grant only
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
        ids["sealed_case"] = str(
            (
                await conn.execute(
                    sa.select(case_record.c.id).where(case_record.c.access_class == "sealed")
                )
            ).scalar_one()
        )
        ids["open_case"] = str(
            (
                await conn.execute(
                    sa.select(case_record.c.id).where(
                        case_record.c.reference == "VRN-N/2026/0001"
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


async def designate(engine, *, case_id: str, user_id: str, by: str) -> None:
    """Put an in-force designation on a case, the way administration would."""
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO case_assignment (id, case_id, user_id, valid_from, valid_to, "
                "assigned_by) VALUES (:i, :c, :u, now() - interval '1 day', NULL, :b)"
            ),
            {"i": str(uuid.uuid4()), "c": case_id, "u": user_id, "b": by},
        )


# --- the seal is real -----------------------------------------------------------


async def test_a_designated_officer_without_clearance_is_denied(api):
    """Designation is decisive for an ordinary case and not sufficient for a seal."""
    client, engine, ids = api
    await designate(engine, case_id=ids["sealed_case"], user_id=ids["officer"],
                    by=ids["cleared"])
    await sign_in(client, ids["officer"])

    assert (await client.get(f"/cases/{ids['sealed_case']}")).status_code == 404


# --- and it can be broken, on the record ----------------------------------------


async def test_break_glass_admits_the_designated_officer(api):
    client, engine, ids = api
    await designate(engine, case_id=ids["sealed_case"], user_id=ids["officer"],
                    by=ids["cleared"])
    await sign_in(client, ids["officer"])

    declared = await client.post(
        f"/cases/{ids['sealed_case']}/break-glass",
        json={"justification": JUSTIFICATION, "minutes": 60},
    )
    assert declared.status_code == 201, declared.text
    assert declared.json()["expires_at"]

    opened = await client.get(f"/cases/{ids['sealed_case']}")
    assert opened.status_code == 200, "the glass was broken and the door did not open"


async def test_an_expired_declaration_does_not_admit(api):
    """Time-bounded means bounded by the clock, re-checked on every request."""
    client, engine, ids = api
    await designate(engine, case_id=ids["sealed_case"], user_id=ids["officer"],
                    by=ids["cleared"])
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO break_glass_access (id, case_id, actor_id, justification, "
                "declared_at, expires_at) VALUES (:i, :c, :u, :j, :d, :e)"
            ),
            {
                "i": str(uuid.uuid4()), "c": ids["sealed_case"], "u": ids["officer"],
                "j": JUSTIFICATION,
                "d": datetime.now(timezone.utc) - timedelta(hours=9),
                "e": datetime.now(timezone.utc) - timedelta(hours=1),
            },
        )
    await sign_in(client, ids["officer"])
    assert (await client.get(f"/cases/{ids['sealed_case']}")).status_code == 404


# --- it is not a master key -----------------------------------------------------


async def test_a_declaration_without_designation_admits_nothing(api):
    """The claim this whole feature stands on.

    A row in `break_glass_access` removes the seal from the subject's path. It is
    never a ground for access. Written directly into the table so the test is about
    the policy rather than about the endpoint's checks.
    """
    client, engine, ids = api
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO break_glass_access (id, case_id, actor_id, justification, "
                "expires_at) VALUES (:i, :c, :u, :j, now() + interval '1 hour')"
            ),
            {"i": str(uuid.uuid4()), "c": ids["sealed_case"], "u": ids["officer"],
             "j": JUSTIFICATION},
        )
    await sign_in(client, ids["officer"])
    assert (await client.get(f"/cases/{ids['sealed_case']}")).status_code == 404, (
        "break-glass admitted a subject with no designation: it is acting as a "
        "ground for access rather than as an exception to the seal"
    )


async def test_a_grantee_cannot_declare_break_glass(api):
    """A grant is the route across an organization boundary. It never opens a seal.

    Arjun holds a live (self-issued) grant on the sealed case. Even a lawful grant
    would not do: letting an external party self-authorize past a seal is worse than
    letting an internal officer do it, because there is nobody upstream to answer for
    it. The rule lives in `policies/break_glass.v1.yaml`, in data.
    """
    client, _, ids = api
    await sign_in(client, ids["grantee"])
    refused = await client.post(
        f"/cases/{ids['sealed_case']}/break-glass",
        json={"justification": JUSTIFICATION, "minutes": 60},
    )
    assert refused.status_code == 404, refused.text


async def test_an_undesignated_officer_cannot_declare(api):
    """404, not 403: no such case and not yours are one answer (threat INS-04)."""
    client, _, ids = api
    await sign_in(client, ids["officer"])
    refused = await client.post(
        f"/cases/{ids['sealed_case']}/break-glass",
        json={"justification": JUSTIFICATION, "minutes": 60},
    )
    assert refused.status_code == 404


async def test_a_cleared_officer_is_told_they_do_not_need_it(api):
    """Nobody should be trained to break glass they can walk through."""
    client, engine, ids = api
    await designate(engine, case_id=ids["sealed_case"], user_id=ids["cleared"],
                    by=ids["cleared"])
    await sign_in(client, ids["cleared"])
    refused = await client.post(
        f"/cases/{ids['sealed_case']}/break-glass",
        json={"justification": JUSTIFICATION, "minutes": 60},
    )
    assert refused.status_code == 409
    assert refused.json()["detail"] == "clearance_sufficient"


async def test_break_glass_on_an_unsealed_case_is_refused(api):
    client, _, ids = api
    await sign_in(client, ids["officer"])          # designated on the open case
    refused = await client.post(
        f"/cases/{ids['open_case']}/break-glass",
        json={"justification": JUSTIFICATION, "minutes": 60},
    )
    assert refused.status_code == 409
    assert refused.json()["detail"] == "case_not_sealed"


# --- what it writes, and what it must not write ---------------------------------


async def test_a_thin_justification_is_refused(api):
    """A one-word reason is not a justification. The record must be worth reading."""
    client, engine, ids = api
    await designate(engine, case_id=ids["sealed_case"], user_id=ids["officer"],
                    by=ids["cleared"])
    await sign_in(client, ids["officer"])
    refused = await client.post(
        f"/cases/{ids['sealed_case']}/break-glass",
        json={"justification": "urgent", "minutes": 60},
    )
    assert refused.status_code == 422


async def test_the_justification_is_never_written_to_the_ledger(api):
    """Invariant 4. The chain carries the id of the record, never its text."""
    client, engine, ids = api
    await designate(engine, case_id=ids["sealed_case"], user_id=ids["officer"],
                    by=ids["cleared"])
    await sign_in(client, ids["officer"])
    declared = await client.post(
        f"/cases/{ids['sealed_case']}/break-glass",
        json={"justification": JUSTIFICATION, "minutes": 60},
    )
    assert declared.status_code == 201

    async with engine.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "SELECT action, object_type, object_id, case_id FROM audit_event "
                    "ORDER BY seq DESC LIMIT 1"
                )
            )
        ).mappings().one()
        stored = (
            await conn.execute(
                sa.text("SELECT justification FROM break_glass_access WHERE id = :i"),
                {"i": row["object_id"]},
            )
        ).scalar_one()

    assert row["action"] == "seal_break_glass"
    assert row["object_type"] == "break_glass"
    assert row["case_id"] == ids["sealed_case"]
    assert stored == JUSTIFICATION, "the audit row does not point at the justification"

    # The whole payload, joined, must not contain the text.
    assert JUSTIFICATION[:30] not in " ".join(str(v) for v in row.values())


async def test_the_record_cannot_be_rewritten(api):
    """Append-only, enforced by the grant rather than by intention (invariant 10).

    A justification that can be edited after the fact is not a justification, it is a
    draft. The app role has INSERT and SELECT on this table and nothing else.
    """
    client, engine, ids = api
    await designate(engine, case_id=ids["sealed_case"], user_id=ids["officer"],
                    by=ids["cleared"])
    await sign_in(client, ids["officer"])
    assert (
        await client.post(
            f"/cases/{ids['sealed_case']}/break-glass",
            json={"justification": JUSTIFICATION, "minutes": 60},
        )
    ).status_code == 201

    with pytest.raises(Exception) as caught:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text("UPDATE break_glass_access SET justification = 'nothing to see'")
            )
    assert "permission denied" in str(caught.value).lower(), caught.value


async def test_a_padded_justification_is_refused_at_the_edge(api):
    """422, not a 500 from the driver.

    `min_length=40` measured the raw string while migration 0013's CHECK measures
    `btrim(justification)`, so `"Urgent." + forty spaces` passed the edge and failed the
    constraint as an unhandled CheckViolation. The rollback also discarded the request's
    own `policy_decision` rows, so a refused attempt left no trace of being refused.
    """
    client, engine, ids = api
    await designate(engine, case_id=ids["sealed_case"], user_id=ids["officer"],
                    by=ids["cleared"])
    await sign_in(client, ids["officer"])

    padded = "Urgent." + " " * 40
    assert len(padded) > 40 and len(padded.strip()) < 40, "this input proves nothing"

    refused = await client.post(
        f"/cases/{ids['sealed_case']}/break-glass",
        json={"justification": padded, "minutes": 60},
    )
    assert refused.status_code == 422, refused.text


async def test_a_refused_declaration_is_still_logged(api):
    """Invariant 3: a deny is a decision, and a decision logs the policy that made it.

    The handler used to run inside one transaction, so raising the refusal rolled back
    the decision rows written on the way to it. A log that keeps only the successes
    cannot answer "was this refused, and why" - which is the question a break-glass
    audit exists for, because somebody attempting a seal they may not break is exactly
    who you want a record of.
    """
    client, engine, ids = api
    await sign_in(client, ids["officer"])          # no designation on the sealed case

    async with engine.connect() as conn:
        before = (
            await conn.execute(sa.text("SELECT count(*) FROM policy_decision"))
        ).scalar_one()

    refused = await client.post(
        f"/cases/{ids['sealed_case']}/break-glass",
        json={"justification": JUSTIFICATION, "minutes": 60},
    )
    assert refused.status_code == 404

    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT policy_id, effect, action FROM policy_decision "
                    "ORDER BY seq DESC LIMIT 2"
                )
            )
        ).mappings().all()
        after = (
            await conn.execute(sa.text("SELECT count(*) FROM policy_decision"))
        ).scalar_one()

    assert after > before, "the refusal rolled back its own decision rows"
    assert any(r["policy_id"] == "ordin.break_glass" for r in rows), rows
    assert all(r["effect"] == "deny" for r in rows), rows


async def test_a_non_uuid_case_id_is_a_404_not_a_500(api):
    client, _, ids = api
    await sign_in(client, ids["officer"])
    refused = await client.post(
        "/cases/not-a-uuid/break-glass",
        json={"justification": JUSTIFICATION, "minutes": 60},
    )
    assert refused.status_code == 404
