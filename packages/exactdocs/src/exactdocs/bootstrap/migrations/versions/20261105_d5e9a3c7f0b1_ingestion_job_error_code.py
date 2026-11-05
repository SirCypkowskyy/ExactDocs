"""Record the stable code of a failed job's error (``repo_unreachable``, ``tag_moved``...).

Revision ID: d5e9a3c7f0b1
Revises: b3d7f1a9c4e2
"""

import sqlalchemy as sa
from alembic import op

revision = "d5e9a3c7f0b1"
down_revision = "b3d7f1a9c4e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingestion_jobs", sa.Column("error_code", sa.Text))


def downgrade() -> None:
    op.drop_column("ingestion_jobs", "error_code")
