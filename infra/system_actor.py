"""The actor a machine stage records, which must not be a person.

`anchor_record.actor_id` is one of the seven fields invariant 4 allows on the chain, and
what it asserts is *who performed this action*. `SimulatedESignProvider.sign` binds the
same id into the HMAC payload, which threat EVD-09 designed precisely so a signature
names its actor.

The worker used to fill that field with
`SELECT id FROM app_user ORDER BY display_name LIMIT 1`. Its docstring defended the
choice on referential grounds — "resolved from the database rather than invented, so
every processing job names a real row" — which answers a question nobody was asking.
The row is real. The claim it makes is false. In the shipped seed that query returns
**PP Arjun Nair, a Public Prosecutor in a different organization**, who under the
authorization model needs an explicit expiring grant to touch a police case at all. The
tamper-evident record then says a prosecutor anchored evidence he never saw, and the one
artefact the system offers as proof of custody carries a provably wrong attribution.

EVD-08 already concedes there is no non-repudiation here. Recording a named, real,
uninvolved officer is worse than recording nothing, because it is a specific false
statement rather than an admitted absence.

So machine stages are attributed to a machine, named as one. CLAUDE.md: never name a
stand-in after the real thing, and never hide a stub behind plausible-looking output.
`Ordin pipeline (automated)` reads as what it is on every screen that shows an actor.

**It holds no post, so it can never be a subject.** `infra/authz.load_subject` joins
`app_user` to `post`, so a NULL `post_id` makes this row unresolvable as a principal —
no organization, no jurisdiction, no clearance, and therefore no route through the
policy. It carries no email or password hash either, so `authenticate` cannot match it.
It is an identifier for attribution and nothing else.

The id is fixed rather than generated, so it is the same row on every machine and in
every export, and `seed()` TRUNCATEs `app_user`, so this is written on demand rather
than once in a migration — a machine that has just been re-seeded still needs it.
"""
import uuid

import sqlalchemy as sa

# A stable, obviously-not-random UUID. Recognisable in a raw anchor row without a join,
# which is the situation somebody auditing the chain is actually in.
SYSTEM_ACTOR_ID = uuid.UUID("00000000-0000-4000-8000-00000000d1ce")
SYSTEM_ACTOR_NAME = "Ordin pipeline (automated)"


async def ensure_system_actor(conn) -> str:
    """Return the system actor id, creating the row if it is not there.

    Idempotent, and safe to call on every batch: `ON CONFLICT DO NOTHING` means a
    concurrent worker doing the same thing is not an error. Written on demand because
    `seed()` truncates `app_user` — a migration-time insert would vanish on the first
    re-seed and the worker would be back to guessing.
    """
    await conn.execute(
        sa.text(
            "INSERT INTO app_user (id, post_id, display_name, clearance_level, is_active) "
            "VALUES (:id, NULL, :name, 0, false) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": SYSTEM_ACTOR_ID, "name": SYSTEM_ACTOR_NAME},
    )
    return str(SYSTEM_ACTOR_ID)
