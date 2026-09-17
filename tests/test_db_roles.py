"""The two-role separation from docs/adr/0001.

Security invariant 10 requires audit rows to be append-only, enforced by revoking
UPDATE and DELETE from the application's database role in the migration.

That control is void if the application connects as the role that owns the table,
because **a table owner is not subject to REVOKE on its own table**. In a default
single-role compose, slice 2's acceptance test would pass while proving nothing.

So the separation is asserted here, in slice 1, before any audit table exists.
If someone later collapses the two roles back into one to make something work,
these fail immediately rather than at slice 2 with a green test and no control.
"""
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.requires_db


async def test_app_role_and_owner_role_are_different_roles(settings):
    assert settings.ordin_app_user != settings.postgres_owner_user, (
        "the application role and the schema owner are the same role; "
        "REVOKE cannot restrain an owner, so invariant 10 is unenforceable"
    )


async def test_app_role_can_connect(live_settings):
    engine = create_async_engine(live_settings.app_dsn)
    try:
        async with engine.connect() as conn:
            who = (await conn.execute(sa.text("SELECT current_user"))).scalar_one()
        assert who == live_settings.ordin_app_user
    finally:
        await engine.dispose()


async def test_app_role_does_not_own_the_public_schema(live_settings):
    engine = create_async_engine(live_settings.app_dsn)
    try:
        async with engine.connect() as conn:
            owner = (
                await conn.execute(
                    sa.text(
                        "SELECT pg_get_userbyid(nspowner) FROM pg_namespace "
                        "WHERE nspname = 'public'"
                    )
                )
            ).scalar_one()
        assert owner != live_settings.ordin_app_user, (
            f"public schema is owned by {owner!r}, which is the application role"
        )
    finally:
        await engine.dispose()


async def test_app_role_cannot_create_tables(live_settings):
    """An object ordin_app created, ordin_app would own - and could then re-grant."""
    engine = create_async_engine(live_settings.app_dsn)
    try:
        async with engine.connect() as conn:
            with pytest.raises(Exception) as exc:
                await conn.execute(sa.text("CREATE TABLE should_not_exist (id int)"))
                await conn.commit()
            assert "permission denied" in str(exc.value).lower(), (
                f"CREATE TABLE failed for the wrong reason: {exc.value}"
            )
    finally:
        await engine.dispose()


async def test_app_role_is_not_a_superuser_and_cannot_bypass_grants(live_settings):
    engine = create_async_engine(live_settings.app_dsn)
    try:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    sa.text(
                        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls "
                        "FROM pg_roles WHERE rolname = current_user"
                    )
                )
            ).one()
        assert not row.rolsuper, "ordin_app is a superuser; every grant is decorative"
        assert not row.rolcreaterole, "ordin_app can create roles, so it can grant itself anything"
        assert not row.rolbypassrls, "ordin_app bypasses row-level security"
    finally:
        await engine.dispose()
