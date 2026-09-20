"""Make case-reference search use an index instead of scanning.

Revision ID: 0011_reference_trigram
Revises: 0010_search

`api/search.py` matches a case reference with a **leading** wildcard:

    reference ILIKE '%' || term || '%'

A plain btree cannot serve that, so `ix_case_record_reference` from migration 0010 was
never used and every reference search was a sequential scan **inside an authorization
subquery**. Free at three seeded cases. Not free at a district's caseload — and the
timing difference is itself a weak side channel on how many cases exist, which is the
kind of leak invariant 1 exists to close.

Prefix matching would use the existing btree and needs no extension, but references are
structured (`VRN-N/2026/0001`) and the useful search is the tail: an officer types
`0001`, not `VRN-N/2026/0001`. Prefix-only would make the feature technically fast and
practically useless.

So: a GIN trigram index, which serves a leading wildcard. `pg_trgm` is a **contrib
extension shipped inside `postgres:16-alpine`**, not a new dependency — nothing to
install, nothing to download, no change to the four-container budget. It is `trusted` in
Postgres 13+, so `ordin_owner` can create it without superuser rights, which matters
because ADR 0001 deliberately leaves nobody here holding superuser.
"""
from alembic import op

revision: str = "0011_reference_trigram"
down_revision: str = "0010_search"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    # The btree from 0010 cannot answer a leading wildcard, so it was only ever
    # occupying disk and misleading whoever read the schema into thinking the query
    # was indexed.
    op.execute("DROP INDEX IF EXISTS ix_case_record_reference")
    op.execute(
        "CREATE INDEX ix_case_record_reference_trgm "
        "ON case_record USING GIN (reference gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_case_record_reference_trgm")
    op.execute("CREATE INDEX ix_case_record_reference ON case_record (reference)")
    # The extension is left in place: another object may have come to depend on it,
    # and dropping it would fail loudly or cascade silently. Neither is what a
    # downgrade should do.
