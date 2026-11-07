"""The spend ledger of AI calls: usage per scope and UTC window (#91; budgets read it in #95).

Revision ID: 9c4e1a7b3f52
Revises: 0c4e8a2f6b19
"""

import sqlalchemy as sa
from alembic import op

revision = "9c4e1a7b3f52"
down_revision = "0c4e8a2f6b19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retrieval_ai_spend",
        sa.Column("scope_kind", sa.Text, primary_key=True),
        sa.Column("scope_id", sa.Text, primary_key=True),
        sa.Column("window_kind", sa.Text, primary_key=True),
        sa.Column("window_start", sa.Text, primary_key=True),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("requests", sa.Integer, nullable=False, server_default="0"),
        sa.Column("usd_micros", sa.Integer, nullable=False, server_default="0"),
        sa.Column("unpriced", sa.Integer, nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("retrieval_ai_spend")
