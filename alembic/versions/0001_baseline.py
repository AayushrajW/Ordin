"""baseline

The empty first revision. It creates no tables on purpose: slice 1 is the
skeleton, and slice 2 introduces the domain model.

What it does establish is that the migration machinery works end to end in both
directions before any schema depends on it — `alembic upgrade head` and
`alembic downgrade base` both run clean, connecting as ordin_owner.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-17
"""
from typing import Sequence, Union

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
