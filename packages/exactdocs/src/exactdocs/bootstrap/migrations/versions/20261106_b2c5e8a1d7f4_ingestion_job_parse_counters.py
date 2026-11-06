"""Job counters of articles parsed and taken as stored before (#164).

Revision ID: b2c5e8a1d7f4
Revises: f8a2d6c4e1b3
"""

import sqlalchemy as sa
from alembic import op

revision = "b2c5e8a1d7f4"
down_revision = "f8a2d6c4e1b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in ("parsed", "taken"):
        op.add_column(
            "ingestion_jobs", sa.Column(column, sa.Integer, nullable=False, server_default="0")
        )


def downgrade() -> None:
    for column in ("taken", "parsed"):
        op.drop_column("ingestion_jobs", column)
