"""Jobs record how their person asked when it was not the web UI or REST (#613).

``created_by_via`` is ``mcp`` for a job an agent queued with ``add_docs``, so an operator can tell
an agent's imports from the UI's. It stays NULL on every other job, earlier ones included.

Revision ID: c4d1a8e93f20
Revises: 4a7c2e9b1d63
"""

import sqlalchemy as sa
from alembic import op

revision = "c4d1a8e93f20"
down_revision = "4a7c2e9b1d63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingestion_jobs", sa.Column("created_by_via", sa.Text))


def downgrade() -> None:
    op.drop_column("ingestion_jobs", "created_by_via")
