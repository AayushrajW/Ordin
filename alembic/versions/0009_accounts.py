"""Accounts: an app_user can now prove who it is, and a post can be administrative.

Revision ID: 0009_accounts
Revises: 0008_source_digest

Until now identity was asserted by picking a name from a list (ADR 0002). The
authorization model never depended on that — the subject is resolved server-side from a
signed token, and every decision is made from the token — so making the proof real is a
change at one boundary, not a rewrite.

**`post_id` becomes nullable.** A person can hold an account before they hold an office.
Signup creates exactly that: an account with no post, and therefore no organization, no
jurisdiction and no clearance. Such a row cannot form a `Subject`, so it is denied
everywhere by construction rather than by a check somebody has to remember to write
(invariant 2). An administrator places them afterwards.

**`post.is_administrative`, not `app_user.is_admin`.** Administration is an office, not a
personal attribute — the same distinction the model already draws between identity and
post (threat DIM-03), and it survives the holder changing. It also keeps invariant 3
intact: the policy evaluator reads this column through a predicate, so administrative
access is decided by versioned policy data like every other access, and the deciding
policy ID is logged. `if user.is_admin` would have been the forbidden hand-rolled check
with a database column behind it.

**Email uniqueness is case-insensitive** via a functional unique index on `lower(email)`,
rather than the citext extension, which would have to be installed in the container.
Two accounts differing only in case are one account to every human being.

`password_hash` is nullable: the seeded specimen identities have no password and cannot
log in, which is correct. They exist to be switched to in development, and
`SimulatedSubjectProvider` refuses to run outside it.
"""
import sqlalchemy as sa
from alembic import op

revision: str = "0009_accounts"
down_revision: str = "0008_source_digest"
branch_labels = None
depends_on = None

APP_ROLE = "ordin_app"


def upgrade() -> None:
    op.add_column("app_user", sa.Column("email", sa.Text(), nullable=True))
    op.add_column("app_user", sa.Column("password_hash", sa.Text(), nullable=True))
    op.add_column(
        "app_user",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column("app_user", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    # Throttling lives on the row as well as in the process-memory limiter, because the
    # limiter resets on restart and is per api process (api/security.py says so).
    op.add_column(
        "app_user",
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("app_user", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))

    # One account per address, whatever case it is typed in.
    op.execute("CREATE UNIQUE INDEX ix_app_user_email ON app_user (lower(email))")

    # An account may exist before it holds an office. Without a post there is no
    # organization, no jurisdiction and no clearance, so no Subject can be formed.
    op.alter_column("app_user", "post_id", existing_type=sa.dialects.postgresql.UUID(), nullable=True)

    op.add_column(
        "post",
        sa.Column("is_administrative", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # ordin_app reads and writes these rows; it owns nothing (docs/adr/0001).
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON app_user TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON post TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_column("post", "is_administrative")
    op.execute("DROP INDEX IF EXISTS ix_app_user_email")
    # Rows created by signup have no post and cannot satisfy NOT NULL again.
    op.execute("DELETE FROM app_user WHERE post_id IS NULL")
    op.alter_column(
        "app_user", "post_id", existing_type=sa.dialects.postgresql.UUID(), nullable=False
    )
    for column in (
        "locked_until",
        "failed_attempts",
        "last_login_at",
        "created_at",
        "password_hash",
        "email",
    ):
        op.drop_column("app_user", column)
