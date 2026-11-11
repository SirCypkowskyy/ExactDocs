"""HyDE's cached hypothetical answers, per manifest, model and query hash (#94).

Revision ID: c3a9e7d1f4b8
Revises: b8e5c3a1f9d7
"""

import sqlalchemy as sa
from alembic import op

revision = "c3a9e7d1f4b8"
down_revision = "b8e5c3a1f9d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retrieval_hyde_answers",
        sa.Column("manifest_id", sa.Text, primary_key=True),
        sa.Column("model", sa.Text, primary_key=True),
        sa.Column("query_hash", sa.Text, primary_key=True),
        sa.Column("answer", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index(
        "ix_retrieval_hyde_answers_created_at", "retrieval_hyde_answers", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_retrieval_hyde_answers_created_at", table_name="retrieval_hyde_answers")
    op.drop_table("retrieval_hyde_answers")
