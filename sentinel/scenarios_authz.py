"""Slice 3's contribution to Sentinel.

Each of these is a claim the pitch makes, expressed as something that can visibly go
red. They run against the live API over HTTP — not against the query layer — because
the claim is about the system a judge can poke, not about a function.

`ctx` carries an httpx client already pointed at the app, plus the seeded identifiers.
"""
from sentinel.registry import Severity, scenario

SLICE = "3"


async def _sign_in(ctx, key: str) -> None:
    response = await ctx.client.post("/session", json={"user_id": ctx.ids[key]})
    assert response.status_code == 200, f"could not open a session: {response.text}"


@scenario(
    id="AUTHZ-01",
    invariant="1 - authorization predicate inside the data query",
    setup="An officer designated on one case of three requests the case list.",
    expected="Fewer cases returned than exist, and the count agrees with the list.",
    severity=Severity.HIGH,
    slice_id=SLICE,
)
async def unauthorized_cases_are_not_listed(ctx) -> str:
    await _sign_in(ctx, "officer")
    listed = (await ctx.client.get("/cases?limit=50")).json()
    counted = (await ctx.client.get("/cases/count")).json()["count"]
    assert len(listed) < ctx.ids["total_cases"], (
        f"the officer saw all {ctx.ids['total_cases']} cases"
    )
    assert counted == len(listed), f"count {counted} disagrees with list {len(listed)}"
    return f"saw {len(listed)} of {ctx.ids['total_cases']} cases; count agreed"


@scenario(
    id="AUTHZ-02",
    invariant="Authorization model - cross-organization access needs a grant, never a role",
    setup="A prosecutor in another organization, holding one case-scoped grant, lists cases.",
    expected="Exactly the granted case, and no other.",
    severity=Severity.HIGH,
    slice_id=SLICE,
)
async def cross_organization_read_needs_a_grant(ctx) -> str:
    await _sign_in(ctx, "grantee")
    listed = (await ctx.client.get("/cases?limit=50")).json()
    assert len(listed) == 1, f"the grantee saw {len(listed)} cases; the grant covers one"
    return "saw exactly the one granted case"


@scenario(
    id="AUTHZ-03",
    invariant="Authorization model - sealed records require clearance beyond ordinary",
    setup="An officer with ordinary clearance fetches a sealed case by id.",
    expected="404, identical to a case that does not exist.",
    severity=Severity.CRITICAL,
    slice_id=SLICE,
)
async def sealed_records_deny_ordinary_clearance(ctx) -> str:
    import uuid

    await _sign_in(ctx, "officer")
    denied = await ctx.client.get(f"/cases/{ctx.ids['sealed_case']}")
    missing = await ctx.client.get(f"/cases/{uuid.uuid4()}")
    assert denied.status_code == 404, f"sealed case returned {denied.status_code}"
    assert denied.json() == missing.json(), (
        "a denied case is distinguishable from a missing one - existence oracle"
    )
    return "404, byte-identical to a nonexistent case"


@scenario(
    id="AUTHZ-04",
    invariant="AZM-06 - the three validity clocks intersect, they do not union",
    setup="A prosecutor holding a LIVE grant whose clearance has lapsed lists cases.",
    expected="Nothing. A live grant does not rescue a lapsed clearance.",
    severity=Severity.CRITICAL,
    slice_id=SLICE,
)
async def a_lapsed_clearance_denies_despite_a_live_grant(ctx) -> str:
    await _sign_in(ctx, "lapsed")
    listed = (await ctx.client.get("/cases?limit=50")).json()
    assert listed == [], f"a lapsed clearance saw {len(listed)} cases"
    return "saw nothing, as the intersection requires"


@scenario(
    id="AUTHZ-05",
    invariant="1 - autocomplete is the worst offender",
    setup="An officer types three letters of a victim name from a sealed case.",
    expected="No suggestion containing that name, while authorized names still appear.",
    severity=Severity.CRITICAL,
    slice_id=SLICE,
)
async def autocomplete_does_not_leak_a_sealed_name(ctx) -> str:
    await _sign_in(ctx, "officer")
    leaked = []
    for prefix in ("Sun", "Kal", "unit"):
        names = [
            s["display_name"]
            for s in (await ctx.client.get(f"/parties/suggest?q={prefix}")).json()
        ]
        leaked += [n for n in names if "Sunita" in n]
    assert not leaked, f"suggestions leaked a sealed-case name: {leaked}"

    # A suggestion box that returns nothing would pass the assertion above trivially.
    authorized = [
        s["display_name"] for s in (await ctx.client.get("/parties/suggest?q=Anj")).json()
    ]
    assert authorized, "no authorized suggestions either - this scenario proves nothing"
    return f"no sealed name across 3 prefixes; {len(authorized)} authorized suggestion(s) still returned"


@scenario(
    id="AUTHZ-06",
    invariant="EXT-02 - identity is resolved server-side, never supplied by the caller",
    setup="Requests carrying X-Role, X-User-Id, X-Clearance and Authorization, with no session.",
    expected="401 for every one. None of them is an identity.",
    severity=Severity.CRITICAL,
    slice_id=SLICE,
)
async def identity_cannot_be_asserted_by_a_header(ctx) -> str:
    ctx.client.cookies.clear()
    statuses = {}
    for header in (
        {"X-Role": "admin"},
        {"X-User-Id": ctx.ids["officer"]},
        {"X-Clearance": "3"},
        {"Authorization": "Bearer anything"},
    ):
        name = next(iter(header))
        statuses[name] = (await ctx.client.get("/cases", headers=header)).status_code
    bad = {k: v for k, v in statuses.items() if v != 401}
    assert not bad, f"headers were honoured as identity: {bad}"
    return f"all {len(statuses)} identity-shaped headers ignored"


@scenario(
    id="AUTHZ-07",
    invariant="3 - every decision logs the policy ID that decided it",
    setup="A denied case fetch, then a read of the decision log.",
    expected="A new row carrying effect, policy_id, policy_version and rule_id.",
    severity=Severity.MEDIUM,
    slice_id=SLICE,
)
async def every_decision_is_attributable(ctx) -> str:
    import sqlalchemy as sa

    await _sign_in(ctx, "officer")
    async with ctx.engine.connect() as conn:
        before = (
            await conn.execute(sa.text("SELECT count(*) FROM policy_decision"))
        ).scalar_one()

    await ctx.client.get(f"/cases/{ctx.ids['sealed_case']}")

    async with ctx.engine.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "SELECT effect, policy_id, policy_version, rule_id "
                    "FROM policy_decision ORDER BY seq DESC LIMIT 1"
                )
            )
        ).mappings().one()
        after = (
            await conn.execute(sa.text("SELECT count(*) FROM policy_decision"))
        ).scalar_one()

    assert after == before + 1, "the denial was not recorded"
    assert row["policy_id"] and row["rule_id"], f"decision row is incomplete: {dict(row)}"
    return (
        f"recorded {row['effect']} by {row['policy_id']} v{row['policy_version']} "
        f"rule {row['rule_id']}"
    )
