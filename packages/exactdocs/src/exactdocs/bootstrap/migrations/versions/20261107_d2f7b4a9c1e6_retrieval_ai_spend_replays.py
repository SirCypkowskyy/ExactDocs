"""Replay tokens of the spend ledger: a replayed LLM response is counted once (#95).

Revision ID: d2f7b4a9c1e6
Revises: 5abe3b929c5f
"""

import sqlalchemy as sa
from alembic import op

revision = "d2f7b4a9c1e6"
down_revision = "5abe3b929c5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retrieval_ai_spend_replays",
        sa.Column("token", sa.Text, primary_key=True),
        sa.Column("scope_kind", sa.Text, primary_key=True),
        sa.Column("scope_id", sa.Text, primary_key=True),
        sa.Column("window_kind", sa.Text, primary_key=True),
        sa.Column("window_start", sa.Text, primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("retrieval_ai_spend_replays")
