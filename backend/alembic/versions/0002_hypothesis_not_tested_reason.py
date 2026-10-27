"""Record why a hypothesis is not tested.

Revision ID: 0002_hypothesis_reason
Revises: 0001_baseline
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_hypothesis_reason"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hypotheses", sa.Column("not_tested_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("hypotheses", "not_tested_reason")
