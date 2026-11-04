"""Job counters (chunked, reused) and at most one unfinished import per library and ref.

Revision ID: a6c2d9e4b3f1
Revises: a91c4e7b3d02
"""

import sqlalchemy as sa
from alembic import op

revision = "a6c2d9e4b3f1"
down_revision = "a91c4e7b3d02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in ("chunked", "reused"):
        op.add_column(
            "ingestion_jobs", sa.Column(column, sa.Integer, nullable=False, server_default="0")
        )
    # The atomic "version_importing": a second queued or running import of a ref cannot be stored.
    op.create_index(
        "ingestion_jobs_active_import",
        "ingestion_jobs",
        ["library", "version"],
        unique=True,
        sqlite_where=sa.text("state IN ('queued', 'running') AND kind IN ('import', 'refresh')"),
    )


def downgrade() -> None:
    op.drop_index("ingestion_jobs_active_import", table_name="ingestion_jobs")
    for column in ("reused", "chunked"):
        op.drop_column("ingestion_jobs", column)
