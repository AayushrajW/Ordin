"""`infra/tables.py` must describe the schema that actually exists.

The authorization filter is built from those Table objects. If a migration renames or
drops a column the filter references, the failure shape depends on where it happens:
a missing column in a WHERE clause raises, but a missing column in an EXISTS subquery
that was supposed to *restrict* could turn into a predicate that restricts nothing.

Cheap to check against the live catalogue, so it is checked rather than assumed.
"""
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from infra.tables import AUTHZ_TABLES

pytestmark = pytest.mark.requires_db


@pytest.fixture
async def conn(live_settings):
    engine = create_async_engine(live_settings.owner_dsn)
    async with engine.connect() as connection:
        yield connection
    await engine.dispose()


async def test_every_declared_table_and_column_exists(conn):
    rows = (
        await conn.execute(
            sa.text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public'"
            )
        )
    ).all()
    actual: dict[str, set[str]] = {}
    for table_name, column_name in rows:
        actual.setdefault(table_name, set()).add(column_name)

    missing = []
    for name, table in AUTHZ_TABLES.items():
        if name not in actual:
            missing.append(f"table {name} does not exist")
            continue
        for column in table.columns:
            if column.name not in actual[name]:
                missing.append(f"{name}.{column.name} does not exist")

    assert not missing, (
        "infra/tables.py describes columns the database does not have:\n  "
        + "\n  ".join(missing)
    )
