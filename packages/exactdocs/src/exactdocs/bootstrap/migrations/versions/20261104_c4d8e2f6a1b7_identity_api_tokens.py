"""Create the identity API tokens table.

Revision ID: c4d8e2f6a1b7
Revises: 7c2e91d4a6b8
"""

import sqlalchemy as sa
from alembic import op

revision = "c4d8e2f6a1b7"
down_revision = "7c2e91d4a6b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identity_api_tokens",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column(
            "account_id",
            sa.Text,
            sa.ForeignKey("identity_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("token_hash", sa.Text, nullable=False, unique=True),
        sa.Column("prefix", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("expires_at", sa.Text),
        sa.Column("last_used_at", sa.Text),
    )
    op.create_index("ix_identity_api_tokens_account_id", "identity_api_tokens", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_identity_api_tokens_account_id", table_name="identity_api_tokens")
    op.drop_table("identity_api_tokens")
