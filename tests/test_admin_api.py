"""Administration (docs/PLAN-PRODUCT.md P3).

The claim that matters is not "an administrator can place people". It is that **an
administrator cannot read a case**. An administration surface is the natural place for
the rule the whole authorization model exists to refuse — seniority as a route to
evidence — and it would arrive looking like a convenience.

Second: administrative capability is decided by `ordin.admin`, a versioned policy file,
and not by a conditional in a route. `tests/test_policy_evaluator.py` already tests
policy files with no app running; this file tests that the routes actually consult one.
"""
import uuid
from datetime import datetime, timezone

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from api.main import create_app
from domain.policy import load_policy
from domain.subject import CaseFacts, Subject
from infra.tables import app_user, case_record

pytestmark = pytest.mark.requires_db

GOOD = "correct horse battery staple"
ADMIN = "administrator password here"


def _address() -> str:
    return f"{uuid.uuid4().hex[:12]}@specimen.invalid"


@pytest.fixture
async def api(live_settings):
    import admin as admin_module
    import seed as seed_module

    await seed_module.seed()
    await admin_module.ensure_admin(
        email="test.admin@specimen.invalid",
        password=ADMIN,
        display_name="Test Administrator",
        settings=live_settings,
    )

    app = create_app(live_settings)
    engine = create_async_engine(live_settings.app_dsn)
    app.state.engine = engine

    ids = {}
    async with engine.connect() as conn:
        ids["officer"] = str(
            (
                await conn.execute(
                    sa.select(app_user.c.id).where(app_user.c.display_name.like("SI Kavya%"))
                )
            ).scalar_one()
        )
        ids["case"] = str(
            (
                await conn.execute(
                    sa.select(case_record.c.id).where(case_record.c.access_class != "sealed")
                    .limit(1)
                )
            ).scalar_one()
        )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        yield client, engine, ids
    await engine.dispose()


async def _sign_in_admin(client) -> None:
    response = await client.post(
        "/auth/login", json={"email": "test.admin@specimen.invalid", "password": ADMIN}
    )
    assert response.status_code == 200, response.text


# --- the claim that matters -----------------------------------------------------


async def test_an_administrator_can_read_no_case(api):
    """Administrative capability routes to no case record, ever.

    `ordin.admin` allowing does not put a single case in reach, because every case route
    runs `ordin.case_read` against the same subject and an administrative post satisfies
    no rule in it.
    """
    client, _, _ = api
    await _sign_in_admin(client)

    cases = await client.get("/cases")
    assert cases.status_code == 200
    assert cases.json() == [], "an administrator was handed case records"

    count = await client.get("/cases/count")
    assert count.status_code == 200
    assert count.json()["count"] == 0, "the count disclosed cases to an administrator"


async def test_the_admin_policy_names_no_predicate_that_reads_the_case(live_settings):
    """A structural guarantee, checked rather than asserted in a comment.

    If someone adds `same_organization` to ordin.admin, administration silently becomes
    organization-scoped case access. The evaluator is handed a neutral CaseFacts, so a
    rule reading the case would be deciding on a placeholder.
    """
    from pathlib import Path

    policy = load_policy(Path("policies") / "admin.v1.yaml")
    case_reading = {
        "assignment_active",
        "same_organization",
        "same_jurisdiction",
        "grant_active",
        "grant_not_self_issued",
        "case_is_sealed",
    }
    named = {c.predicate for rule in policy.rules for c in rule.conditions}
    assert not (named & case_reading), (
        f"ordin.admin names case-reading predicates {sorted(named & case_reading)}; "
        "it is evaluated against a placeholder case, so these decide on nothing real"
    )


async def test_an_ordinary_account_cannot_reach_administration(api):
    """And is not told that administration exists."""
    client, engine, ids = api
    address = _address()
    await client.post(
        "/auth/signup", json={"email": address, "password": GOOD, "display_name": "Ordinary"}
    )
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE app_user SET is_active = true, "
                "post_id = (SELECT id FROM post WHERE NOT is_administrative LIMIT 1) "
                "WHERE lower(email) = :e"
            ),
            {"e": address},
        )
    await client.post("/auth/login", json={"email": address, "password": GOOD})

    for path in ("/admin/users", "/admin/posts", "/admin/cases", "/admin/access"):
        response = await client.get(path)
        assert response.status_code == 404, (
            f"{path} answered {response.status_code} to a non-administrator; 403 would "
            "confirm the surface exists"
        )


async def test_an_administrator_whose_clearance_lapsed_stops_being_one(api):
    """The three clocks intersect for administration exactly as for case access."""
    client, engine, _ = api
    await _sign_in_admin(client)
    assert (await client.get("/admin/users")).status_code == 200

    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE app_user SET clearance_valid_to = '2020-01-01T00:00:00+00' "
                "WHERE lower(email) = 'test.admin@specimen.invalid'"
            )
        )
    assert (await client.get("/admin/users")).status_code == 404, (
        "a lapsed clearance left administrative capability intact"
    )


# --- placing accounts -----------------------------------------------------------


async def test_placing_an_account_makes_it_usable_but_still_opens_no_case(api):
    client, engine, ids = api
    address = _address()
    await client.post(
        "/auth/signup", json={"email": address, "password": GOOD, "display_name": "Newcomer"}
    )
    await _sign_in_admin(client)

    posts = (await client.get("/admin/posts")).json()
    ordinary = next(p for p in posts if not p["is_administrative"])

    users = (await client.get("/admin/users")).json()
    newcomer = next(u for u in users if u["email"] == address)
    assert newcomer["placed"] is False

    placed = await client.post(
        f"/admin/users/{newcomer['user_id']}/place",
        json={"post_id": ordinary["post_id"], "clearance_level": 1, "is_active": True},
    )
    assert placed.status_code == 200, placed.text

    # Now sign in as them: they have a post, and still no case.
    await client.post("/auth/logout")
    await client.post("/auth/login", json={"email": address, "password": GOOD})
    assert (await client.get("/cases")).json() == [], (
        "placing an account handed it cases; a post is not a designation"
    )


async def test_assigning_to_a_case_is_what_opens_it(api):
    """The whole point of the administration surface, end to end."""
    client, engine, ids = api
    address = _address()
    await client.post(
        "/auth/signup", json={"email": address, "password": GOOD, "display_name": "Assignee"}
    )
    await _sign_in_admin(client)

    posts = (await client.get("/admin/posts")).json()
    users = (await client.get("/admin/users")).json()
    assignee = next(u for u in users if u["email"] == address)

    # Place them in the organization that owns the case, or designation will not hold:
    # the rule requires assignment AND same organization AND same jurisdiction.
    async with engine.connect() as conn:
        org = (
            await conn.execute(
                sa.text(
                    "SELECT o.name FROM case_record c JOIN organization o "
                    "ON o.id = c.organization_id WHERE c.id = :c"
                ),
                {"c": ids["case"]},
            )
        ).scalar_one()
    post = next(p for p in posts if p["organization"] == org and not p["is_administrative"])

    await client.post(
        f"/admin/users/{assignee['user_id']}/place",
        json={"post_id": post["post_id"], "clearance_level": 1, "is_active": True},
    )
    assigned = await client.post(
        "/admin/assignments", json={"user_id": assignee["user_id"], "case_id": ids["case"]}
    )
    assert assigned.status_code == 200, assigned.text

    await client.post("/auth/logout")
    await client.post("/auth/login", json={"email": address, "password": GOOD})
    cases = (await client.get("/cases")).json()
    assert len(cases) == 1, f"designation did not open the case: {cases}"


async def test_an_unplaced_account_cannot_be_designated(api):
    """A designation held by an account with no organization grants nothing.

    It would be a row that looks like access and confers none — the worst kind of
    administrative action, because the screen would report success.
    """
    client, _, ids = api
    address = _address()
    await client.post(
        "/auth/signup", json={"email": address, "password": GOOD, "display_name": "Unplaced"}
    )
    await _sign_in_admin(client)
    users = (await client.get("/admin/users")).json()
    unplaced = next(u for u in users if u["email"] == address)

    response = await client.post(
        "/admin/assignments", json={"user_id": unplaced["user_id"], "case_id": ids["case"]}
    )
    assert response.status_code in (400, 404), response.text


# --- grants ---------------------------------------------------------------------


async def test_an_administrator_cannot_grant_access_to_themselves(api):
    """Refused at write time as well as at read time.

    `grant_not_self_issued` already refuses it when the policy runs. Refusing the write
    too means the row never exists to be reasoned about, and AR-15 is one case smaller.
    """
    client, engine, ids = api
    await _sign_in_admin(client)
    async with engine.connect() as conn:
        admin_id = str(
            (
                await conn.execute(
                    sa.text(
                        "SELECT id FROM app_user WHERE lower(email) = "
                        "'test.admin@specimen.invalid'"
                    )
                )
            ).scalar_one()
        )
    response = await client.post(
        "/admin/grants",
        json={"grantee_id": admin_id, "case_id": ids["case"], "purpose": "reading it",
              "days": 30},
    )
    assert response.status_code == 400, response.text


async def test_a_grant_opens_a_case_and_revoking_closes_it_immediately(api):
    client, engine, ids = api
    address = _address()
    await client.post(
        "/auth/signup", json={"email": address, "password": GOOD, "display_name": "Grantee"}
    )
    await _sign_in_admin(client)

    posts = (await client.get("/admin/posts")).json()
    users = (await client.get("/admin/users")).json()
    grantee = next(u for u in users if u["email"] == address)
    post = next(p for p in posts if not p["is_administrative"])
    await client.post(
        f"/admin/users/{grantee['user_id']}/place",
        json={"post_id": post["post_id"], "clearance_level": 1, "is_active": True},
    )

    issued = await client.post(
        "/admin/grants",
        json={"grantee_id": grantee["user_id"], "case_id": ids["case"],
              "purpose": "charge-sheet preparation", "days": 30},
    )
    assert issued.status_code == 200, issued.text
    grant_id = issued.json()["grant_id"]

    await client.post("/auth/logout")
    await client.post("/auth/login", json={"email": address, "password": GOOD})
    assert len((await client.get("/cases")).json()) == 1, "the grant opened no case"

    # Revoke, and the same session loses it on the very next request.
    await client.post("/auth/logout")
    await _sign_in_admin(client)
    revoked = await client.post(f"/admin/grants/{grant_id}/revoke")
    assert revoked.status_code == 200, revoked.text

    await client.post("/auth/logout")
    await client.post("/auth/login", json={"email": address, "password": GOOD})
    assert (await client.get("/cases")).json() == [], (
        "revocation did not take effect on the next request"
    )


async def test_current_access_answers_who_can_see_what(api):
    """AR-14 named the absence of this. It is answerable now."""
    client, _, _ = api
    await _sign_in_admin(client)
    response = await client.get("/admin/access")
    assert response.status_code == 200
    body = response.json()
    assert "designations" in body and "grants" in body
    assert any(d["reference"] for d in body["designations"]), body
