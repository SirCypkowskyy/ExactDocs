"""Create the ingestion jobs table.

Revision ID: 5f3a9c21d7b4
Revises: ac89e0a428cd
"""

import sqlalchemy as sa
from alembic import op

revision = "5f3a9c21d7b4"
down_revision = "ac89e0a428cd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("library", sa.Text, nullable=False),
        sa.Column("version", sa.Text),
        sa.Column(
            "state",
            sa.Text,
            sa.CheckConstraint("state IN ('queued', 'running', 'succeeded', 'failed')"),
            nullable=False,
        ),
        sa.Column("done", sa.Integer, nullable=False),
        sa.Column("total", sa.Integer, nullable=False),
        sa.Column("problems", sa.Text, nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("started_at", sa.Text),
        sa.Column("finished_at", sa.Text),
    )
    op.create_index("ingestion_jobs_library", "ingestion_jobs", ["library", "created_at"])
    op.create_index("ingestion_jobs_state", "ingestion_jobs", ["state"])


def downgrade() -> None:
    op.drop_table("ingestion_jobs")
