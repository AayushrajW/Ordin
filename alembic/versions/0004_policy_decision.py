"""policy_decision

Security invariant 3: "every decision logs the policy ID that decided it."

The columns are the control. There is deliberately no free-text field: a decision log
that records *why* in prose is a decision log that eventually records a party name
(invariant 12). What a row holds is identifiers, the effect, and the rule id - which
is enough to replay the decision against the versioned policy file that produced it.

Append-only, for the same reason audit_event is: a decision record that can be edited
afterwards answers the question you want it to answer rather than the one you asked.
The REVOKE below binds only because ordin_app does not own the table (docs/adr/0001).

Revision ID: 0004_policy_decision
Revises: 0003_domain_model
Create Date: 2026-09-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_policy_decision"
down_revision: Union[str, None] = "0003_domain_model"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_ROLE = "ordin_app"


def upgrade() -> None:
    op.create_table(
        "policy_decision",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        # Who asked. The post is recorded alongside the user because identity and
        # post are two dimensions, and a decision replayed later needs to know which
        # office the person held at the time (threat DIM-03).
        sa.Column("subject_user_id", sa.Uuid(), nullable=False),
        sa.Column("subject_post_id", sa.Uuid(), nullable=False),
        # What was asked about. Type plus id, never a human-readable reference.
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False, server_default="read"),
        # What was decided, and by which version of which rule.
        sa.Column("effect", sa.Text(), nullable=False),
        sa.Column("policy_id", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Text(), nullable=False),
        # Correlation id ties a decision to the request that caused it, so a
        # decision and its audit event can be read together.
        sa.Column("correlation_id", sa.Text(), nullable=True),
        sa.CheckConstraint("effect IN ('allow','deny')", name="ck_policy_decision_effect"),
    )
    op.create_index(
        "ix_policy_decision_subject", "policy_decision", ["subject_user_id", "decided_at"]
    )
    op.create_index(
        "ix_policy_decision_resource", "policy_decision", ["resource_type", "resource_id"]
    )

    op.execute(f"GRANT SELECT, INSERT ON policy_decision TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON policy_decision FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("policy_decision")
