"""Core table definitions for the authorization surface.

Explicit `sa.Table` objects rather than reflection or an ORM layer. Three reasons:

  - The authorization filter needs column objects at import time, not after a
    round trip to the database.
  - Listing the columns here makes the authorization surface visible. A policy can
    only reference what is defined, and what is defined is deliberately the minimum.
  - CLAUDE.md keeps the domain layer framework-free; these live in `infra/` where
    SQLAlchemy is allowed.

These mirror `alembic/versions/0003_domain_model.py`. They are not the whole schema -
only what authorization reads. `test_tables_match_the_migration` asserts every table
and column named here actually exists in the migrated database, so a migration that
renames a column fails a test rather than producing a silently wider query.
"""
import sqlalchemy as sa

metadata = sa.MetaData()

case_record = sa.Table(
    "case_record",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("reference", sa.Text()),
    sa.Column("organization_id", sa.Uuid()),
    sa.Column("jurisdiction_id", sa.Uuid()),
    sa.Column("state", sa.Text()),
    sa.Column("access_class", sa.Text()),
)

case_assignment = sa.Table(
    "case_assignment",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("case_id", sa.Uuid()),
    sa.Column("user_id", sa.Uuid()),
    sa.Column("valid_from", sa.DateTime(timezone=True)),
    sa.Column("valid_to", sa.DateTime(timezone=True)),
)

access_grant = sa.Table(
    "access_grant",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("grantee_id", sa.Uuid()),
    sa.Column("case_id", sa.Uuid()),
    sa.Column("purpose", sa.Text()),
    sa.Column("expires_at", sa.DateTime(timezone=True)),
    sa.Column("granted_by", sa.Uuid()),
    sa.Column("revoked_at", sa.DateTime(timezone=True)),
)

app_user = sa.Table(
    "app_user",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("post_id", sa.Uuid()),
    sa.Column("display_name", sa.Text()),
    sa.Column("clearance_level", sa.Integer()),
    sa.Column("clearance_valid_to", sa.DateTime(timezone=True)),
    sa.Column("is_active", sa.Boolean()),
)

post = sa.Table(
    "post",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("organization_id", sa.Uuid()),
    sa.Column("jurisdiction_id", sa.Uuid()),
    sa.Column("title", sa.Text()),
    # Administration is an office, not a personal attribute (migration 0009).
    sa.Column("is_administrative", sa.Boolean()),
)

party = sa.Table(
    "party",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("case_id", sa.Uuid()),
    sa.Column("role", sa.Text()),
    sa.Column("display_name", sa.Text()),
)

# What the SQL predicate builders receive. Keyed by name so a policy predicate can
# ask for a table without importing this module's globals.
AUTHZ_TABLES = {
    "case_record": case_record,
    "case_assignment": case_assignment,
    "access_grant": access_grant,
    "app_user": app_user,
    "post": post,
    "party": party,
}
