"""Baseline: the schema created by database/schema.sql.

After running schema.sql on a new database, mark it as up to date with:

    cd backend && alembic stamp 0001_baseline

Later schema changes are added as new revisions (alembic revision --autogenerate).

Revision ID: 0001_baseline
Revises:
"""
revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Nothing to do: database/schema.sql already created these tables."""


def downgrade() -> None:
    """The baseline cannot be downgraded; drop the database instead."""
