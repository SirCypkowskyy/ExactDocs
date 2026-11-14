"""Each library's own retrieval mode (RET-06), stored by retrieval.

Revision ID: a7c3e9b1d5f2
Revises: b2c5e8a1d7f4
"""

import sqlalchemy as sa
from alembic import op

revision = "a7c3e9b1d5f2"
down_revision = "b2c5e8a1d7f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retrieval_library_settings",
        sa.Column("library", sa.Text, primary_key=True),
        sa.Column("mode", sa.Text),
    )


def downgrade() -> None:
    op.drop_table("retrieval_library_settings")
