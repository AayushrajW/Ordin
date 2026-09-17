"""system_heartbeat

**This is infrastructure, not domain.** It is not a case-record entity and does not
pre-empt slice 2's domain model. It exists so that `/health` can say something true
about the worker: the worker has no jobs until slice 5a, so without a shared signal
its health check would be decorative.

One row per component. The worker updates its row on a loop; the api reads it. A
green worker therefore proves two things at once — the process is alive, and it can
reach the database as ordin_app.

Revision ID: 0002_system_heartbeat
Revises: 0001_baseline
Create Date: 2026-09-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_system_heartbeat"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_heartbeat",
        sa.Column("component", sa.Text(), primary_key=True),
        sa.Column(
            "beat_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # ordin_app needs DML here. ALTER DEFAULT PRIVILEGES in db/init/01-roles.sh
    # already grants it for tables ordin_owner creates, but stating it explicitly
    # means this migration is correct even applied to a database initialised by
    # some other route.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON system_heartbeat TO ordin_app")


def downgrade() -> None:
    op.drop_table("system_heartbeat")
