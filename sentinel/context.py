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
    return ids
