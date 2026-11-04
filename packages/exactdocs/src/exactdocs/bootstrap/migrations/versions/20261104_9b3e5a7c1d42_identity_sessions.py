"""Create the identity sessions table.

Revision ID: 9b3e5a7c1d42
Revises: 5f87041a0ed2
"""

import sqlalchemy as sa
from alembic import op

revision = "9b3e5a7c1d42"
down_revision = "5f87041a0ed2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identity_sessions",
        sa.Column("token_hash", sa.Text, primary_key=True),
        sa.Column(
            "account_id",
            sa.Text,
            sa.ForeignKey("identity_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("last_used_at", sa.Text, nullable=False),
    )
    op.create_index("ix_identity_sessions_account_id", "identity_sessions", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_identity_sessions_account_id", table_name="identity_sessions")
    op.drop_table("identity_sessions")
