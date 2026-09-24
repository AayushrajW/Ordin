"""Export is a verb, and a verb can be counted (AR-17).

Revision ID: 0014_export_accounting
Revises: 0013_break_glass

Threat AR-17: "Bulk export is unmetered. A designated officer can export every case
they hold at 2am, lawfully, with no quota or anomaly detection." Its stated mitigation
is deliberately modest and is the one that fits this budget: **make export a distinct
verb in the audit chain recording row count and filter - accounting, not prevention.**

Nothing here stops anybody. It makes the question answerable: how many documents left,
under whose name, through which disclosure class, and when. Before this, reading a
document and taking a copy of it were the same event to the system, which meant the
difference between an officer working a case and an officer emptying it was invisible.

**Every column is enumerated or numeric. There is no `filter` text column**, although
AR-17's wording invites one. A free-text field on a record like this is where a case
reference, a party name or a search term eventually lands - written by somebody being
helpful - and invariant 12 forbids exactly that. The `disclosure` class and the counts
answer the question without ever holding a word of the case.

The audit row carries the id of the row below; the numbers live here, for the same
reason the break-glass justification does (invariant 4 fixes the chain's payload).
"""
import sqlalchemy as sa
from alembic import op

revision: str = "0014_export_accounting"
down_revision: str = "0013_break_glass"
branch_labels = None
depends_on = None

APP_ROLE = "ordin_app"


def upgrade() -> None:
    op.create_table(
        "export_record",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("case_record.id"), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        # 'version' is one document leaving; 'case' is the bulk verb AR-17 names.
        sa.Column("scope", sa.Text(), nullable=False),
        # Which class of bytes left. An export under a purpose-limited grant carries
        # derivatives only, and a record that could not say which is not accounting.
        sa.Column("disclosure", sa.Text(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("byte_count", sa.BigInteger(), nullable=False),
        # Versions deliberately left out of the bundle because they did not verify.
        # Counted rather than hidden: an export that silently dropped a tampered
        # document would be the quietest possible way to lose the alert.
        sa.Column("excluded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("scope IN ('version','case')", name="ck_export_scope"),
        sa.CheckConstraint(
            "disclosure IN ('original','redacted')", name="ck_export_disclosure"
        ),
        sa.CheckConstraint("row_count >= 0 AND byte_count >= 0", name="ck_export_counts"),
    )
    # "What did this person take, and when" is the query this table exists for.
    op.create_index("ix_export_actor", "export_record", ["actor_id", "exported_at"])
    op.create_index("ix_export_case", "export_record", ["case_id", "exported_at"])

    op.execute(f"GRANT SELECT, INSERT ON export_record TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON export_record FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("ix_export_case", table_name="export_record")
    op.drop_index("ix_export_actor", table_name="export_record")
    op.drop_table("export_record")
