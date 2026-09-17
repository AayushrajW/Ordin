"""Alembic environment.

Migrations connect as **ordin_owner**, never as ordin_app. That is the whole point
of docs/adr/0001: the role that owns the schema must not be the role the running
application uses, or slice 2's `REVOKE UPDATE, DELETE ON audit_events` is a no-op
against a table owner and security invariant 10 becomes unenforceable.
"""
import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.config import Settings  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Slice 2 sets this to the domain metadata. Until then there is nothing to
# autogenerate against, and saying so is better than importing a placeholder.
target_metadata = None

settings = Settings()
config.set_main_option("sqlalchemy.url", settings.owner_dsn)


def run_migrations_offline() -> None:
    context.configure(
        url=settings.owner_dsn,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
