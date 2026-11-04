"""Create the table of encrypted library credentials.

Revision ID: a1c9e4d7b352
Revises: a6c2d9e4b3f1
"""

import sqlalchemy as sa
from alembic import op

revision = "a1c9e4d7b352"
down_revision = "a6c2d9e4b3f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingestion_library_credentials",
        sa.Column("library", sa.Text, primary_key=True),
        sa.Column("sealed", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ingestion_library_credentials")
