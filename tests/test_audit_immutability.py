"""Security invariant 10, the half that arithmetic cannot provide.

`test_audit_chain.py` proves the chain detects an altered row. This proves the
application's database role cannot alter one in the first place.

The reason this is a slice-2 test with a slice-1 precondition: **a table owner is not
subject to REVOKE on its own table.** If the application connected as the role that
owns the schema, the REVOKE below would be a no-op and every assertion here would pass
while the control did nothing. That is why docs/adr/0001 put two roles in slice 1, and
why `test_grants_are_actually_revoked` checks the catalogue directly rather than
trusting that a failed UPDATE means what it appears to mean.
"""
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from domain.enums import AuditAction
from infra.audit_log import append_audit

pytestmark = pytest.mark.requires_db


@pytest.fixture
async def app_engine(live_settings):
    """Connected as ordin_app — the restricted runtime role."""
    engine = create_async_engine(live_settings.app_dsn)
    yield engine
    await engine.dispose()


@pytest.fixture
async def owner_engine(live_settings):
    """Connected as ordin_owner — used only to set up rows the app role then cannot touch."""
    engine = create_async_engine(live_settings.owner_dsn)
    yield engine
    await engine.dispose()


async def seed_one_audit_row(engine) -> int:
    """Insert a row as the app role and return its seq. Inserting is allowed.

    Through `append_audit` rather than a hand-written INSERT, even though this file
    is about grants and not about hashes. An earlier version wrote `prev_row_hash`
    and `row_hash` as constants, which was harmless here and quietly corrosive
    elsewhere: `audit_event` has no DELETE grant and `seed.py` spares it, so those
    rows are permanent, and any claim that the chain verifies end to end became false
    the first time this test ran. Sentinel scenario AUDIT-01 makes that claim.
    """
    async with engine.begin() as conn:
        await append_audit(
            conn,
            case_id="case-immut",
            actor_id="user-immut",
            action=AuditAction.DOCUMENT_VIEWED,
            object_type="document",
            object_id="doc-immut",
        )
        return (
            await conn.execute(sa.text("SELECT max(seq) FROM audit_event"))
        ).scalar_one()


# --- the control itself ------------------------------------------------------

async def test_app_role_can_append(app_engine):
    """Append-only means append IS allowed; otherwise nothing could be audited."""
    seq = await seed_one_audit_row(app_engine)
    assert isinstance(seq, int)


async def test_app_role_cannot_update_an_audit_row(app_engine):
    seq = await seed_one_audit_row(app_engine)
    with pytest.raises(Exception) as exc:
        async with app_engine.begin() as conn:
            await conn.execute(
                sa.text("UPDATE audit_event SET actor_id = 'someone-else' WHERE seq = :s"),
                {"s": seq},
            )
    assert "permission denied" in str(exc.value).lower(), (
        f"UPDATE failed for the wrong reason: {exc.value}"
    )


async def test_app_role_cannot_delete_an_audit_row(app_engine):
    seq = await seed_one_audit_row(app_engine)
    with pytest.raises(Exception) as exc:
        async with app_engine.begin() as conn:
            await conn.execute(sa.text("DELETE FROM audit_event WHERE seq = :s"), {"s": seq})
    assert "permission denied" in str(exc.value).lower()


async def test_app_role_cannot_truncate_the_audit_table(app_engine):
    """TRUNCATE is a distinct privilege from DELETE and is easy to forget."""
    with pytest.raises(Exception) as exc:
        async with app_engine.begin() as conn:
            await conn.execute(sa.text("TRUNCATE audit_event"))
    assert "permission denied" in str(exc.value).lower() or "must be owner" in str(exc.value).lower()


# --- proving the test would fail if the REVOKE were removed ------------------

async def test_grants_are_actually_revoked_in_the_catalogue(app_engine, live_settings):
    """Check the grant directly, not just that a statement failed.

    An UPDATE can fail for many reasons. This asserts the specific privileges are
    absent, so the test cannot pass for an accidental reason.
    """
    async with app_engine.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT privilege_type FROM information_schema.role_table_grants "
                    "WHERE table_name = 'audit_event' AND grantee = :g"
                ),
                {"g": live_settings.ordin_app_user},
            )
        ).scalars().all()
    granted = {r.upper() for r in rows}
    assert "INSERT" in granted, "the app role cannot append - nothing could be audited"
    assert "SELECT" in granted, "the app role cannot read the audit log"
    assert "UPDATE" not in granted, "UPDATE is still granted; invariant 10 is unenforced"
    assert "DELETE" not in granted, "DELETE is still granted; invariant 10 is unenforced"


async def test_the_app_role_does_not_own_the_audit_table(app_engine, live_settings):
    """The precondition the whole control rests on. See docs/adr/0001."""
    async with app_engine.connect() as conn:
        owner = (
            await conn.execute(
                sa.text(
                    "SELECT tableowner FROM pg_tables WHERE tablename = 'audit_event'"
                )
            )
        ).scalar_one()
    assert owner != live_settings.ordin_app_user, (
        f"audit_event is owned by {owner!r}, the application role - REVOKE cannot "
        f"restrain an owner, so every other assertion in this file is vacuous"
    )


# --- the revoke is targeted, not a blanket read-only role --------------------

async def test_the_app_role_can_still_write_ordinary_tables(app_engine):
    """If ordin_app were read-only everywhere, the audit REVOKE would prove nothing."""
    async with app_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO system_heartbeat (component, beat_at) VALUES ('immut-probe', now()) "
                "ON CONFLICT (component) DO UPDATE SET beat_at = now()"
            )
        )
        await conn.execute(sa.text("DELETE FROM system_heartbeat WHERE component = 'immut-probe'"))
