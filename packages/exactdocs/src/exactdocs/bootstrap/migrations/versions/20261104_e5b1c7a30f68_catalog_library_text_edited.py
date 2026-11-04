"""Remember which of a library's title and description a user typed (README imports keep them).

Revision ID: e5b1c7a30f68
Revises: d7e2a4b9c150
"""

import sqlalchemy as sa
from alembic import op

revision = "e5b1c7a30f68"
down_revision = "d7e2a4b9c150"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in ("title_edited", "description_edited"):
        op.add_column(
            "catalog_libraries",
            sa.Column(column, sa.Boolean, nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    for column in ("title_edited", "description_edited"):
        op.drop_column("catalog_libraries", column)
