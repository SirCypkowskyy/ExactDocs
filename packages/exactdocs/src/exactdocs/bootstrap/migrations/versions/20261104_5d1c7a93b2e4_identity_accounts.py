"""Create the identity tables.

Revision ID: 5d1c7a93b2e4
Revises: f421064ebb87
"""

import sqlalchemy as sa
from alembic import op

revision = "5d1c7a93b2e4"
down_revision = "f421064ebb87"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identity_accounts",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("username", sa.Text, nullable=False, unique=True),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("identity_accounts")
