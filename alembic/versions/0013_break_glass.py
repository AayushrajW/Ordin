"""Break-glass: the seal has an exception, and the exception leaves a record.

Revision ID: 0013_break_glass
Revises: 0012_document_class

A deny with no exception is a design that gets worked around. The officer who needs a
sealed file at 2am and cannot open it does not go home - they ring somebody with
clearance and use their session, and the system records the wrong person reading the
wrong file for a reason nobody wrote down. Break-glass is the cheaper trade: the
exception is available, it is bounded, and taking it costs a written justification and
a row on the audit chain.

**Why the justification lives here and not on the chain.** Invariant 4 fixes what an
audit row may carry - `case_id, doc_id, version, sha256, actor_id, action, utc_ts` -
and a free-text column on the audit table is exactly where a case summary, a victim's
name or a witness's address eventually lands. So the chain carries this row's id and
this table carries the words. The audit row still cannot be rewritten, and neither can
this one.

**Append-only, with no revocation column.** A declaration cannot be edited after the
fact, because a justification that can be rewritten is a draft. There is deliberately
no `revoked_at`: the window is minutes to hours and it closes by itself, so revocation
would be a column that exists to look thorough. Shortening the maximum window is the
control; a revoke button on a sixty-minute grant is theatre.

The minimum length is enforced in the database as well as at the edge, because a value
the application never writes can still arrive from a fixture loader or a hand-typed
INSERT, and an empty justification would make the record worthless exactly when
somebody is reading it to decide whether the access was proper.
"""
import sqlalchemy as sa
from alembic import op

revision: str = "0013_break_glass"
down_revision: str = "0012_document_class"
branch_labels = None
depends_on = None

APP_ROLE = "ordin_app"

# Long enough that "urgent" and "need it" do not qualify, short enough that a real
# sentence does. A justification nobody can act on later is not a control.
MINIMUM_JUSTIFICATION = 40


def upgrade() -> None:
    op.create_table(
        "break_glass_access",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("case_record.id"), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("app_user.id"), nullable=False),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("declared_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        # Which policy said this subject was eligible to declare. Invariant 3 wants
        # every decision explainable, and "who let them break the glass" is the
        # question this table exists to answer.
        sa.Column("policy_decision_seq", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            f"length(btrim(justification)) >= {MINIMUM_JUSTIFICATION}",
            name="ck_break_glass_justification_length",
        ),
        sa.CheckConstraint("expires_at > declared_at", name="ck_break_glass_window"),
    )
    # The authorization predicate looks up (case, actor, expiry) on every request that
    # touches a sealed case, so it is an index rather than a scan.
    op.create_index(
        "ix_break_glass_lookup", "break_glass_access", ["case_id", "actor_id", "expires_at"]
    )

    # Invariant 10's reasoning, applied to a second table: this only means anything
    # because ordin_app is not the owner (docs/adr/0001). TRUNCATE is a distinct
    # privilege from DELETE and is revoked separately.
    op.execute(f"GRANT SELECT, INSERT ON break_glass_access TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON break_glass_access FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("ix_break_glass_lookup", table_name="break_glass_access")
    op.drop_table("break_glass_access")
