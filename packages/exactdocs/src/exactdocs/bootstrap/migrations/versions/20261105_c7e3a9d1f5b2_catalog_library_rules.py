"""A library keeps the rules of its default version's ``context7.json`` (LIB-06).

Revision ID: c7e3a9d1f5b2
Revises: d4f8b2c6e9a3
"""

import sqlalchemy as sa
from alembic import op

revision = "c7e3a9d1f5b2"
down_revision = "d4f8b2c6e9a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "catalog_libraries",
        sa.Column("rules", sa.Text, nullable=False, server_default="[]"),  # a JSON list
    )


def downgrade() -> None:
    op.drop_column("catalog_libraries", "rules")
