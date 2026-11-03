"""Create the catalog tables.

Revision ID: ac89e0a428cd
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "ac89e0a428cd"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_libraries",
        sa.Column("name", sa.Text, primary_key=True),
    )
    op.create_table(
        "catalog_library_versions",
        sa.Column(
            "library_name",
            sa.Text,
            sa.ForeignKey("catalog_libraries.name", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.Text, primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("catalog_library_versions")
    op.drop_table("catalog_libraries")
