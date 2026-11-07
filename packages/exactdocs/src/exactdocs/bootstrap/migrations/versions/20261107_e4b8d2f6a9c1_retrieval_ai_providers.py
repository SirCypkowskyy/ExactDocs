"""AI provider profiles stored over the REST API, and each library's AI overrides (#241).

Revision ID: e4b8d2f6a9c1
Revises: 2a34523e0d8e
"""

import sqlalchemy as sa
from alembic import op

revision = "e4b8d2f6a9c1"
down_revision = "2a34523e0d8e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retrieval_ai_providers",
        sa.Column("name", sa.Text, primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("settings", sa.Text, nullable=False),
        sa.Column("sealed_key", sa.Text),
    )
    op.add_column(
        "retrieval_library_settings",
        sa.Column("ai_enabled", sa.Integer, nullable=False, server_default="1"),
    )
    for column in ("llm", "judge", "reranker"):
        op.add_column("retrieval_library_settings", sa.Column(column, sa.Text))


def downgrade() -> None:
    for column in ("reranker", "judge", "llm", "ai_enabled"):
        op.drop_column("retrieval_library_settings", column)
    op.drop_table("retrieval_ai_providers")
