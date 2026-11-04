"""Record what a job's version is (tag, branch or commit), so an import need not ask the remote.

Revision ID: d7e2a4b9c150
Revises: c3a8e1f94b27
"""

import sqlalchemy as sa
from alembic import op

revision = "d7e2a4b9c150"
down_revision = "c3a8e1f94b27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingestion_jobs", sa.Column("ref_kind", sa.Text))


def downgrade() -> None:
    op.drop_column("ingestion_jobs", "ref_kind")
