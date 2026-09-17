"""anchor_record and disposition

CLAUDE.md invariant 4 fixes what an anchor may carry:

    case_id, doc_id, version, sha256, actor_id, action, utc_ts

Exactly those, plus the two chain columns. There is no title, no reference, no party
and no filename here, and the narrowness is the control: "no PII on the ledger, ever"
is enforceable only if there is nowhere for PII to go.

`version_id` is UNIQUE. That is what makes anchoring idempotent - a retry must not
produce a second anchor (reliability invariant), and a constraint enforces it where a
code path merely intends it.

`disposition` records a lawful destruction. `verify()` needs it to distinguish
DISPOSED_ANCHOR_ONLY from "the bytes are gone and we cannot say why", which is the
difference between a legal record and an incident.

Both tables are append-only for the app role, same reasoning as audit_event: a
destruction record you can edit afterwards does not evidence anything.

Revision ID: 0005_integrity
Revises: 0004_policy_decision
Create Date: 2026-09-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_integrity"
down_revision: Union[str, None] = "0004_policy_decision"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_ROLE = "ordin_app"


def upgrade() -> None:
    op.create_table(
        "anchor_record",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        # --- invariant 4's tuple, and nothing else ---
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False, server_default="anchor"),
        sa.Column("utc_ts", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        # --- the chain ---
        sa.Column("prev_row_hash", sa.Text(), nullable=False),
        sa.Column("row_hash", sa.Text(), nullable=False),
        sa.CheckConstraint("length(content_sha256) = 64", name="ck_anchor_digest_length"),
    )
    op.create_index("ix_anchor_record_case", "anchor_record", ["case_id"])

    op.create_table(
        "disposition",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("version_id", sa.Uuid(), sa.ForeignKey("document_version.id"),
                  nullable=False, unique=True),
        sa.Column("disposed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("disposed_by", sa.Uuid(), sa.ForeignKey("app_user.id"), nullable=False),
        # Enumerated, never free text: a "reason" field on a destruction record is
        # where a case summary eventually lands (invariant 12).
        sa.Column("basis", sa.Text(), nullable=False),
        sa.Column("policy_decision_seq", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "basis IN ('retention_expiry','court_order','erroneous_upload','superseded_original')",
            name="ck_disposition_basis",
        ),
    )

    for table in ("anchor_record", "disposition"):
        op.execute(f"GRANT SELECT, INSERT ON {table} TO {APP_ROLE}")
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("disposition")
    op.drop_table("anchor_record")
