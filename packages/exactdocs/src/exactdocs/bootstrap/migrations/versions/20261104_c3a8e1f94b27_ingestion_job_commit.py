"""Record the commit a job's version was pinned to.

Revision ID: c3a8e1f94b27
Revises: 7c2e91d4a6b8
"""

import sqlalchemy as sa
from alembic import op

revision = "c3a8e1f94b27"
down_revision = "7c2e91d4a6b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingestion_jobs", sa.Column("commit_sha", sa.Text))


def downgrade() -> None:
    op.drop_column("ingestion_jobs", "commit_sha")
