"""The identifiers every scenario needs, resolved once.

Shared by the CLI runner and the dashboard route so the two cannot drift into
running the same scenarios against different subjects — which would make one of them
green and the other red for reasons nobody could see.

Scenarios address subjects by *role in the story* ("officer", "grantee", "lapsed")
rather than by name or id. That is what lets the seed change a display name without
silently repointing a security scenario at a different person.
"""
import importlib
import pkgutil

import sqlalchemy as sa

from infra.tables import app_user, case_record


def load_scenarios() -> int:
    """Import every `sentinel/scenarios_*.py`, which is what registers them.

    Discovered rather than listed. Three places needed the list — the CLI runner, the
    dashboard route and the test — and the test's copy fell behind: slice 5b added four
    scenarios and the pytest suite kept running eleven, so the new ones were only ever
    exercised by hand. A registry that depends on somebody remembering to add an import
    is a registry that silently shrinks.

    Returns the number of registered scenarios, so a caller can assert it found some.
    """
    import sentinel
    from sentinel.registry import REGISTRY

    for module in pkgutil.iter_modules(sentinel.__path__):
        if module.name.startswith("scenarios_"):
            importlib.import_module(f"sentinel.{module.name}")
    return len(REGISTRY)

# display-name prefix -> the name scenarios use. The prefix is matched, not the whole
# name, so the seed can carry surnames without every scenario file knowing them.
SUBJECTS = {
    "officer": "SI Kavya",
    "lapsed": "PP Meera",
    "grantee": "PP Arjun",
    # Clearance 3, so sealed records are open to them. The negative subject for every
    # sealed-record claim needs a positive one to be worth anything.
    "cleared": "SHO Rahul",
}


async def load_ids(conn) -> dict:
    ids: dict = {}
    for key, fragment in SUBJECTS.items():
        ids[key] = str(
            (
                await conn.execute(
                    sa.select(app_user.c.id).where(
                        app_user.c.display_name.like(f"{fragment}%")
                    )
                )
            ).scalar_one()
        )
    # **A sealed case this officer has no route to** - which is what AUTHZ-03 and
    # SEAL-01 both actually mean by "the sealed case", and neither of them said.
    #
    # This was `scalar_one()` over every sealed case, which held only while exactly one
    # existed. SEAL-02 registers a sealed case per run, so the second run crashed the
    # suite with MultipleResultsFound before a scenario ran. Narrowing it to
    # `ORDER BY reference LIMIT 1` then picked one of SEAL-02's own cases - `SNT-` sorts
    # before `VRN-` - on which the officer IS designated, so two scenarios asserting
    # that a sealed case is unreachable failed against a case that was reachable on
    # purpose. Both attempts were the same mistake: naming the fixture by an incidental
    # property instead of by the relationship the claim depends on.
    ids["sealed_case"] = str(
        (
            await conn.execute(
                sa.text(
                    "SELECT c.id FROM case_record c "
                    "WHERE c.access_class = 'sealed' "
                    "  AND NOT EXISTS ( "
                    "    SELECT 1 FROM case_assignment a "
                    "    WHERE a.case_id = c.id AND a.user_id = :officer "
                    "      AND a.valid_from <= now() "
                    "      AND (a.valid_to IS NULL OR a.valid_to > now())) "
                    "ORDER BY c.reference LIMIT 1"
                ),
                {"officer": ids["officer"]},
            )
        ).scalar_one()
    )
    # **The case the story is told about, chosen by the relationships it carries.**
    #
    # Scenarios used to reach for `(await client.get("/cases"))[0]` - the officer's
    # first case by reference. That is a fixture assumption wearing a computation's
    # clothes: it holds only while the seed is the only thing that registers cases.
    # SEAL-02 registers one per run under an `SNT-` prefix, which sorts before `VRN-`,
    # so `cases[0]` silently became a case the GRANTEE has no grant on - and VERIFY-03,
    # whose entire subject is what a grantee is offered, received a 404 body and failed
    # with a TypeError rather than a claim.
    #
    # Named by what the scenarios actually need: a case the officer is designated on
    # AND the grantee holds a live, non-self-issued grant on.
    ids["primary_case"] = str(
        (
            await conn.execute(
                sa.text(
                    "SELECT c.id FROM case_record c "
                    "JOIN case_assignment a ON a.case_id = c.id AND a.user_id = :officer "
                    "  AND a.valid_from <= now() "
                    "  AND (a.valid_to IS NULL OR a.valid_to > now()) "
                    "JOIN access_grant g ON g.case_id = c.id AND g.grantee_id = :grantee "
                    "  AND g.expires_at > now() AND g.revoked_at IS NULL "
                    "  AND g.granted_by <> g.grantee_id "
                    "ORDER BY c.reference LIMIT 1"
                ),
                {"officer": ids["officer"], "grantee": ids["grantee"]},
            )
        ).scalar_one()
    )
    ids["total_cases"] = (
        await conn.execute(sa.select(sa.func.count()).select_from(case_record))
    ).scalar_one()
    return ids
