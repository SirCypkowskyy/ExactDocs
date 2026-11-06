"""The libraries' scheduled checks (SYNC-02), and the origin a job gives the version it imports.

Revision ID: f8a2d6c4e1b3
Revises: e3b7c1d9a4f2
"""

import sqlalchemy as sa
from alembic import op

revision = "f8a2d6c4e1b3"
down_revision = "e3b7c1d9a4f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingestion_jobs", sa.Column("origin", sa.Text, nullable=False, server_default="manual")
    )
    op.create_table(
        "ingestion_auto_syncs",
        sa.Column("library", sa.Text, primary_key=True),
        sa.Column("tag_pattern", sa.Text),
        sa.Column("keep_last", sa.Integer, nullable=False),
        sa.Column("interval_minutes", sa.Integer, nullable=False),
        sa.Column("sync_branches", sa.Boolean, nullable=False),
        sa.Column("checked_at", sa.Text),
        sa.Column("last_error", sa.Text),
        sa.Column("revision", sa.Text, nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_table("ingestion_auto_syncs")
    op.drop_column("ingestion_jobs", "origin")
