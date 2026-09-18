"""Run Sentinel from the command line: `python tasks.py sentinel`.

The dashboard page is slice 8. This is the same scenarios, printed - which is what
makes them useful now rather than at hour 28, and what lets a judge watch one go red
by breaking something on purpose.
"""
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sentinel.scenarios_authz  # noqa: F401,E402 - importing registers them
import sentinel.scenarios_redaction  # noqa: F401,E402
import sentinel.scenarios_verification  # noqa: F401,E402
from api.config import Settings  # noqa: E402
from api.main import create_app  # noqa: E402
from infra.tables import app_user, case_record  # noqa: E402
from sentinel.registry import Outcome, run_all  # noqa: E402


@dataclass
class Ctx:
    client: httpx.AsyncClient
    engine: object
    ids: dict
    # The same store the api serves bytes from, so a scenario that pushes a document
    # through the pipeline produces one the running app can then render.
    blobs: object = None


async def main() -> int:
    settings = Settings()
    app = create_app(settings)
    engine = create_async_engine(settings.app_dsn)
    app.state.engine = engine

    ids = {}
    async with engine.connect() as conn:
        for fragment, key in (("SI Kavya", "officer"), ("PP Meera", "lapsed"),
                              ("PP Arjun", "grantee")):
            ids[key] = str((await conn.execute(
                sa.select(app_user.c.id).where(app_user.c.display_name.like(f"{fragment}%"))
            )).scalar_one())
        ids["sealed_case"] = str((await conn.execute(
            sa.select(case_record.c.id).where(case_record.c.access_class == "sealed")
        )).scalar_one())
        ids["total_cases"] = (await conn.execute(
            sa.select(sa.func.count()).select_from(case_record)
        )).scalar_one()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://sentinel") as client:
        results = await run_all(
            Ctx(client=client, engine=engine, ids=ids, blobs=app.state.blobs)
        )
    await engine.dispose()

    mark = {Outcome.PASS: "PASS", Outcome.FAIL: "FAIL", Outcome.ERROR: "ERR "}
    print("\nOrdin Sentinel\n")
    for r in results:
        print(f"  [{mark[r.outcome]}] {r.id}  ({r.severity})")
        print(f"         invariant: {r.invariant}")
        print(f"         setup:     {r.setup}")
        print(f"         expected:  {r.expected}")
        print(f"         actual:    {r.actual}")
        print()
    bad = [r for r in results if not r.ok]
    print(f"  {len(results) - len(bad)}/{len(results)} passing")
    if bad:
        print(f"  {len(bad)} NOT passing: {', '.join(r.id for r in bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
