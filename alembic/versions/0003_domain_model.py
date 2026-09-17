"""domain model

The entity set is trimmed from BOOTSTRAP's 16 to the 12 the golden thread and slice 3
actually need. Deferred deliberately, each to the slice that owns its shape:

  Clearance       -> columns on app_user. It is a level plus a validity window, and a
                     table would add a join for nothing at this scale.
  PolicyDecision  -> slice 3, which writes it and should decide its columns.
  ExtractedField  -> slice 5a. Invariant 7 requires source_span/confidence/provider/
                     model/prompt_version, and there is an unresolved question about
                     manual entry producing a field with no span. Better to answer
                     that before freezing a schema than to freeze the wrong one.
  AnchorRecord    -> slice 4a, with verify() and LocalAnchorStore.

Naming: `case` and `user` are reserved words in SQL, so the tables are `case_record`
and `app_user`. Quoting reserved identifiers everywhere is a papercut that eventually
gets forgotten in a raw query.

Revision ID: 0003_domain_model
Revises: 0002_system_heartbeat
Create Date: 2026-09-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_domain_model"
down_revision: Union[str, None] = "0002_system_heartbeat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_ROLE = "ordin_app"


def upgrade() -> None:
    # --- organizational structure -------------------------------------------
    # Organization (who employs you) and jurisdiction (where you have authority)
    # are separate dimensions and are never conflated. Cross-organization access
    # always needs an explicit grant, never a role.
    op.create_table(
        "organization",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_table(
        "jurisdiction",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
    )
    op.create_table(
        "post",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("jurisdiction_id", sa.Uuid(), sa.ForeignKey("jurisdiction.id"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
    )
    # Identity and post are two dimensions, not one (threat DIM-03). A user holds a
    # post; assignments key on the user, grants key on the user. Keeping that
    # consistent is the point - an inconsistent mix is where succession leaks.
    op.create_table(
        "app_user",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("post_id", sa.Uuid(), sa.ForeignKey("post.id"), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("clearance_level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("clearance_valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    # --- the case record ----------------------------------------------------
    op.create_table(
        "case_record",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("reference", sa.Text(), nullable=False, unique=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("jurisdiction_id", sa.Uuid(), sa.ForeignKey("jurisdiction.id"), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default="registered"),
        sa.Column("access_class", sa.Text(), nullable=False, server_default="normal"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    # Sealing is ordered at case level as well as version level (threat DIM-07);
    # slice 3 evaluates the seal by join from here, with the version flag narrowing.
    op.create_table(
        "party",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("case_record.id"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
    )
    # Append-only with a validity window rather than deleted on un-assignment, so a
    # self-designate / read / un-designate cycle stays permanently visible
    # (threat INS-09) and revocation is a data change, not a schema change later.
    op.create_table(
        "case_assignment",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("case_record.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assigned_by", sa.Uuid(), sa.ForeignKey("app_user.id"), nullable=True),
    )
    op.create_index("ix_case_assignment_case_user", "case_assignment", ["case_id", "user_id"])

    # --- documents ----------------------------------------------------------
    op.create_table(
        "document",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("case_record.id"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    # lifecycle_state and access_class are independent axes: a document can be sealed
    # AND superseded. Modelling them as one status column is the classic error.
    op.create_table(
        "document_version",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("document.id"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("metadata_sha256", sa.Text(), nullable=True),
        sa.Column("lifecycle_state", sa.Text(), nullable=False, server_default="active"),
        sa.Column("access_class", sa.Text(), nullable=False, server_default="normal"),
        sa.Column("derived_from_version_id", sa.Uuid(),
                  sa.ForeignKey("document_version.id"), nullable=True),
        sa.Column("redaction_manifest_hash", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("document_id", "version_no", name="uq_document_version_no"),
    )

    # --- pipeline -----------------------------------------------------------
    # idempotency_key is SHA256(case_id || content_sha256 || operation || params_hash)
    # per docs/adr/0004. UNIQUE is what actually enforces "a retry must not produce a
    # second version, extraction run, anchor or derivative".
    op.create_table(
        "processing_job",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_version_id", sa.Uuid(),
                  sa.ForeignKey("document_version.id"), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("maturity", sa.Text(), nullable=True),
        # Enumerated codes only. Persisting raw exception text here would carry
        # document content back out over the job-status route (threat CD-01).
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_processing_job_claim", "processing_job", ["status", "created_at"])

    # --- authorization data -------------------------------------------------
    # Always case-scoped (docs/adr/0005). There is no representation for an
    # organization-wide grant: no nullable case_id, no wildcard.
    op.create_table(
        "access_grant",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("grantee_id", sa.Uuid(), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("case_record.id"), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("granted_by", sa.Uuid(), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_access_grant_lookup", "access_grant", ["grantee_id", "case_id"])

    # --- audit --------------------------------------------------------------
    # seq is the insertion order the chain is verified in. IDs and decisions only:
    # no document content, no party names, no free text (invariant 12).
    op.create_table(
        "audit_event",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("object_type", sa.Text(), nullable=False),
        sa.Column("object_id", sa.Text(), nullable=False),
        sa.Column("utc_ts", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("prev_row_hash", sa.Text(), nullable=False),
        sa.Column("row_hash", sa.Text(), nullable=False),
    )
    op.create_index("ix_audit_event_case", "audit_event", ["case_id", "seq"])

    # Security invariant 10. This is the line that matters, and it only means
    # anything because ordin_app is not the owner of this table (docs/adr/0001).
    # TRUNCATE is revoked separately: it is a distinct privilege from DELETE.
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON audit_event FROM {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON audit_event TO {APP_ROLE}")

    # Everything else the application legitimately writes.
    for table in (
        "organization", "jurisdiction", "post", "app_user", "case_record", "party",
        "case_assignment", "document", "document_version", "processing_job", "access_grant",
    ):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")


def downgrade() -> None:
    for table in (
        "audit_event", "access_grant", "processing_job", "document_version", "document",
        "case_assignment", "party", "case_record", "app_user", "post", "jurisdiction",
        "organization",
    ):
        op.drop_table(table)
