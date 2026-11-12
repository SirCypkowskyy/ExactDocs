"""The spend ledger keeps the tokens of local models apart: no token budget counts them (#284).

Revision ID: b5e8d2a7c4f9
Revises: e4b7c2d9a6f1
"""

import sqlalchemy as sa
from alembic import op

revision = "b5e8d2a7c4f9"
down_revision = "e4b7c2d9a6f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "retrieval_ai_spend",
        sa.Column("local_tokens", sa.Integer, nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("retrieval_ai_spend", "local_tokens")
