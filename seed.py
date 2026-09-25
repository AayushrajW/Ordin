#!/usr/bin/env python
"""Demo seed: 3 cases across 2 organizations.

Run with `python tasks.py seed`.

Everything here is **visibly synthetic**, per CLAUDE.md's honesty rules: fictional
names, fictional station codes. This is structural seed data — organizations, posts,
users, cases, parties, assignments — not the document corpus, which slice 6a generates
with `SPECIMEN — NOT A REAL RECORD` on every page.

The shape is chosen to make slice 3's authorization tests meaningful rather than to
look impressive:

  - Two organizations, so cross-organization denial has something to deny.
  - An officer designated on one case and not another, so "seniority does not imply
    access to a case you are not assigned to" is testable.
  - A lapsed assignment (valid_to in the past) and an expired grant, so the three
    independent validity clocks can be tested separately (threat AZM-06).
  - A sealed case, so unclearanced access has a target.
"""
import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.config import Settings  # noqa: E402
from infra import suite_guard  # noqa: E402

NOW = datetime.now(timezone.utc)


def uid() -> uuid.UUID:
    return uuid.uuid4()


async def seed() -> int:
    settings = Settings()

    # **Refuse while a test suite is using this database.** `seed()` TRUNCATEs the case
    # tables, so running it under a live suite deletes rows that suite is mid-way
    # through asserting on - and the failure lands in a different test each run, reading
    # as flakiness. tests/conftest.py has refused a second *pytest* session for exactly
    # this reason since the day the cause was found; the check lives in
    # infra/suite_guard.py now because pytest was never the only caller. demo.py calls
    # seed(), `python seed.py` calls seed(), and so does any one-off script somebody
    # writes to poke the running API - which is precisely how this gap surfaced.
    lock = suite_guard.lock_path(
        settings.postgres_host, settings.postgres_port, settings.postgres_db
    )
    holder = suite_guard.held_by_another_process(lock)
    if holder is not None:
        print(suite_guard.refusal_message(lock, settings.postgres_db, holder))
        return 2

    engine = create_async_engine(settings.owner_dsn)

    org_police, org_pros = uid(), uid()
    jur_north, jur_south = uid(), uid()
    post_si, post_sho, post_pp = uid(), uid(), uid()
    user_kavya, user_rahul, user_meera, user_arjun = uid(), uid(), uid(), uid()
    case_a, case_b, case_c = uid(), uid(), uid()

    try:
        async with engine.begin() as conn:
            # Idempotent: wipe the structural seed, leave migrations alone.
            #
            # CASCADE rather than a hand-ordered DELETE list. The list approach broke
            # twice - once when `disposition` arrived and once when `extracted_field`
            # did - because every new table with a foreign key into this set silently
            # invalidates the ordering. CASCADE follows the constraints the database
            # already knows about, so a table added in a later slice needs no edit here.
            #
            # The audit trail is deliberately NOT in this list: audit_event,
            # policy_decision and anchor_record hold no foreign keys into it, so CASCADE
            # cannot reach them. A seed that wiped the audit log would be destroying the
            # one thing that is supposed to be append-only.
            #
            # **Two append-only tables ARE reached, and that is correct.**
            # `break_glass_access` and `export_record` (migrations 0013, 0014) carry
            # foreign keys into `case_record` and `app_user`, so CASCADE removes their
            # rows with the cases they describe. Append-only means the *application*
            # cannot rewrite them; it does not mean a row outlives the case it points
            # at, and leaving orphans behind would be worse. Worth stating because the
            # paragraph above reads, at a glance, as a promise that no append-only table
            # is touched here - and that has not been true since 0013.
            await conn.execute(
                sa.text(
                    "TRUNCATE organization, jurisdiction, post, app_user, case_record, "
                    "party, case_assignment, document, document_version, access_grant "
                    "RESTART IDENTITY CASCADE"
                )
            )
    
            await conn.execute(
                sa.text("INSERT INTO organization (id, name, kind) VALUES "
                        "(:a, 'Vranaspur City Police', 'police'), "
                        "(:b, 'Vranaspur District Prosecution', 'prosecution')"),
                {"a": org_police, "b": org_pros},
            )
            await conn.execute(
                sa.text("INSERT INTO jurisdiction (id, name, code) VALUES "
                        "(:a, 'Vranaspur North', 'VRN-N'), (:b, 'Vranaspur South', 'VRN-S')"),
                {"a": jur_north, "b": jur_south},
            )
            await conn.execute(
                sa.text("INSERT INTO post (id, organization_id, jurisdiction_id, title) VALUES "
                        "(:p1, :police, :north, 'Sub-Inspector'), "
                        "(:p2, :police, :north, 'Station House Officer'), "
                        "(:p3, :pros,   :south, 'Public Prosecutor')"),
                {"p1": post_si, "p2": post_sho, "p3": post_pp,
                 "police": org_police, "pros": org_pros, "north": jur_north, "south": jur_south},
            )
            await conn.execute(
                sa.text("INSERT INTO app_user (id, post_id, display_name, clearance_level, "
                        "clearance_valid_to) VALUES "
                        "(:u1, :si,  'SI Kavya Raut',   1, NULL), "
                        "(:u2, :sho, 'SHO Rahul Desai', 3, :future), "
                        "(:u3, :pp,  'PP Meera Nadkarni', 2, :past), "
                        "(:u4, :pp,  'PP Arjun Nair',     2, :future)"),
                {"u1": user_kavya, "u2": user_rahul, "u3": user_meera, "u4": user_arjun,
                 "si": post_si, "sho": post_sho, "pp": post_pp,
                 "future": NOW + timedelta(days=365), "past": NOW - timedelta(days=1)},
            )
    
            # Case C is sealed; case B sits in the other jurisdiction.
            await conn.execute(
                sa.text("INSERT INTO case_record (id, reference, organization_id, "
                        "jurisdiction_id, state, access_class) VALUES "
                        "(:a, 'VRN-N/2026/0001', :police, :north, 'under_investigation', 'normal'), "
                        "(:b, 'VRN-S/2026/0002', :police, :south, 'registered', 'normal'), "
                        "(:c, 'VRN-N/2026/0003', :police, :north, 'filed', 'sealed')"),
                {"a": case_a, "b": case_b, "c": case_c,
                 "police": org_police, "north": jur_north, "south": jur_south},
            )
            await conn.execute(
                sa.text("INSERT INTO party (id, case_id, role, display_name) VALUES "
                        "(:p1, :a, 'complainant', 'Ms Anjali Bhosle'), "
                        "(:p2, :a, 'witness',     'Mr Prakash Iyer'), "
                        "(:p3, :c, 'victim',      'Ms Sunita Kale')"),
                {"p1": uid(), "p2": uid(), "p3": uid(), "a": case_a, "c": case_c},
            )
    
            # Kavya is designated on case A only - case B is the negative case for
            # "designation is decisive". Her assignment to case C has LAPSED.
            await conn.execute(
                sa.text("INSERT INTO case_assignment (id, case_id, user_id, valid_from, valid_to, "
                        "assigned_by) VALUES "
                        "(:i1, :a, :kavya, :long_ago, NULL,     :rahul), "
                        "(:i2, :c, :kavya, :long_ago, :yesterday, :rahul), "
                        "(:i3, :a, :rahul, :long_ago, NULL,     :rahul)"),
                {"i1": uid(), "i2": uid(), "i3": uid(),
                 "a": case_a, "c": case_c, "kavya": user_kavya, "rahul": user_rahul,
                 "long_ago": NOW - timedelta(days=30), "yesterday": NOW - timedelta(days=1)},
            )
    
            # The prosecutors are in a different organization: they reach a case only
            # through an explicit, purpose-limited, expiring grant, never through a role.
            # Arjun's clearance is current; Meera's has lapsed, so she is the case that
            # proves the three validity clocks intersect rather than union (AZM-06) -
            # a live grant does not save a lapsed clearance.
            await conn.execute(
                sa.text("INSERT INTO access_grant (id, grantee_id, case_id, purpose, expires_at, "
                        "granted_by) VALUES "
                        "(:g1, :arjun, :a, 'charge-sheet preparation', :future, :rahul), "
                        "(:g2, :meera, :a, 'charge-sheet preparation', :future, :rahul), "
                        "(:g3, :arjun, :b, 'charge-sheet preparation', :past,   :rahul), "
                        # g4 is self-issued: lawful at every instant, and exactly why
                        # the grant_not_self_issued predicate exists (threat INS-10).
                        "(:g4, :arjun, :c, 'case review', :future, :arjun)"),
                {"g1": uid(), "g2": uid(), "g3": uid(), "g4": uid(),
                 "meera": user_meera, "arjun": user_arjun, "rahul": user_rahul,
                 "a": case_a, "b": case_b, "c": case_c,
                 "future": NOW + timedelta(days=30), "past": NOW - timedelta(days=2)},
            )
    
        async with engine.connect() as conn:
            counts = {}
            for table in ("organization", "case_record", "app_user", "case_assignment",
                          "access_grant", "party"):
                counts[table] = (
                    await conn.execute(sa.text(f"SELECT count(*) FROM {table}"))
                ).scalar_one()
    finally:
        await engine.dispose()

    for name, n in counts.items():
        print(f"  {name:18} {n}")
    print("\n  seeded: 3 cases across 2 organizations")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(seed()))
