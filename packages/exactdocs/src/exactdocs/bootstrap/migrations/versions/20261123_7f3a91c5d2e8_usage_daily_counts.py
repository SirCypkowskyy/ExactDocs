"""Usage counts (#510): how often each person, token and library reads, searches and asks.

``usage_daily_counts`` holds one row per UTC day, account, API token, library and operation
(``read``, ``search``, ``answer``) with the number of requests: no query, no path, no text. An
empty account, token or library means none (no person, a browser session, an operation over
several libraries). Accounts, tokens and libraries are held by value (the usage domain owns no
other table), and rows older than the retention are deleted by the nightly upkeep. This revision
only creates the table, so it can follow any other revision of the same day.

Revision ID: 7f3a91c5d2e8
Revises: e2b6c94f1a37
"""

import sqlalchemy as sa
from alembic import op

revision = "7f3a91c5d2e8"
down_revision = "e2b6c94f1a37"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_daily_counts",
        sa.Column("day", sa.Text, nullable=False),
        sa.Column("account_id", sa.Text, nullable=False),
        sa.Column("token_id", sa.Text, nullable=False),
        sa.Column("library", sa.Text, nullable=False),
        sa.Column("operation", sa.Text, nullable=False),
        sa.Column("requests", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("day", "account_id", "token_id", "library", "operation"),
    )
    op.create_index(
        "ix_usage_daily_counts_account_day", "usage_daily_counts", ["account_id", "day"]
    )


def downgrade() -> None:
    op.drop_index("ix_usage_daily_counts_account_day", table_name="usage_daily_counts")
    op.drop_table("usage_daily_counts")
