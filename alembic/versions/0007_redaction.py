"""redaction_manifest and redaction_region

A redacted derivative is a first-class version (it already has
`derived_from_version_id` and `redaction_manifest_hash` from slice 2). This adds the
manifest those point at.

**The manifest never stores the text it removed** (threat VIC-04). The obvious,
defensible design - log what was redacted so the redaction can be justified later -
produces a curated list of exactly the identifying strings in the document, which is
a worse artefact than the original: shorter, and entirely composed of names.

So a region records geometry, the rule that selected it, and a **salted hash** of the
removed text. That is enough to answer "was this particular name redacted here?" when
someone already knows the name and is checking, and useless for discovering names.
The salt is per-manifest, so the same name in two documents does not produce the same
hash and the set cannot be cross-referenced.

Access: the manifest is authorized strictly ABOVE the derivative. Someone who may see
the redacted copy must not be able to read the list of what was taken out of it.

Revision ID: 0007_redaction
Revises: 0006_pipeline
Create Date: 2026-09-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_redaction"
down_revision: Union[str, None] = "0006_pipeline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_ROLE = "ordin_app"


def upgrade() -> None:
    op.create_table(
        "redaction_manifest",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("derivative_version_id", sa.Uuid(),
                  sa.ForeignKey("document_version.id"), nullable=False, unique=True),
        sa.Column("parent_version_id", sa.Uuid(),
                  sa.ForeignKey("document_version.id"), nullable=False),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("case_record.id"), nullable=False),
        # Per-manifest, so the same name in two documents hashes differently and the
        # manifests cannot be cross-referenced to build a name list.
        sa.Column("salt", sa.Text(), nullable=False),
        sa.Column("manifest_hash", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )

    op.create_table(
        "redaction_region",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("manifest_id", sa.Uuid(), sa.ForeignKey("redaction_manifest.id"),
                  nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("x0", sa.Float(), nullable=False),
        sa.Column("y0", sa.Float(), nullable=False),
        sa.Column("x1", sa.Float(), nullable=False),
        sa.Column("y1", sa.Float(), nullable=False),
        # Which rule selected this region - a field key, never the value.
        sa.Column("rule_id", sa.Text(), nullable=False),
        # Salted hash of what was removed. There is deliberately no column that could
        # hold the text itself.
        sa.Column("removed_hash", sa.Text(), nullable=False),
        sa.CheckConstraint("x1 > x0 AND y1 > y0", name="ck_region_rect"),
    )
    op.create_index("ix_redaction_region_manifest", "redaction_region", ["manifest_id"])

    for table in ("redaction_manifest", "redaction_region"):
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {APP_ROLE}")
        # A manifest that can be edited after the fact cannot justify anything.
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE redaction_region_id_seq TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("redaction_region")
    op.drop_table("redaction_manifest")
