"""document_version records what was received as well as what is held.

Revision ID: 0008_source_digest
Revises: 0007_redaction

Slice 4b put sanitisation in front of version creation, and version identity is the
digest of the *stored* bytes. That made the identity of an upload depend on the
sanitiser producing byte-identical output every time — and PyMuPDF does not quite
guarantee that. `sanitise` is deterministic in a clean process, and across a long-lived
one its output occasionally differs by a few bytes as mupdf compacts object numbering
differently. The visible symptom was the pipeline's idempotency tests failing
intermittently in full runs and passing in isolation, in a different test each time.

Making the *upload's* digest the identity removes the dependency entirely: whatever the
sanitiser emits, the same received bytes in the same case are the same version.

It also answers a question the schema could not: **what did we actually receive?**
`sha256` is what the system holds and anchors; `source_sha256` is what arrived. When
they differ, something was removed — and `redaction_manifest` aside, that difference was
previously invisible.

Nullable, because rows created before this migration have no recorded source. The
lookup falls back to `sha256` for those.
"""
import sqlalchemy as sa
from alembic import op

revision: str = "0008_source_digest"
down_revision: str = "0007_redaction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_version",
        sa.Column("source_sha256", sa.Text(), nullable=True),
    )
    # The lookup `_upsert_version` performs on every ingest.
    op.create_index(
        "ix_document_version_source",
        "document_version",
        ["document_id", "source_sha256"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_version_source", table_name="document_version")
    op.drop_column("document_version", "source_sha256")
