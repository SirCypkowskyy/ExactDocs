"""The agentic answer cache, per manifest, model, scope fingerprint and question hash (#100).

Revision ID: e4b7c2d9a6f1
Revises: f1d6a8c3e5b2
"""

import sqlalchemy as sa
from alembic import op

revision = "e4b7c2d9a6f1"
down_revision = "f1d6a8c3e5b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retrieval_agentic_answers",
        sa.Column("manifest_id", sa.Text, primary_key=True),
        sa.Column("model", sa.Text, primary_key=True),
        sa.Column("fingerprint", sa.Text, primary_key=True),
        sa.Column("question_hash", sa.Text, primary_key=True),
        sa.Column("library", sa.Text, nullable=False),
        sa.Column("similarity", sa.Text, nullable=False),
        sa.Column("terms", sa.Text, nullable=False),
        sa.Column("guards", sa.Text, nullable=False),
        sa.Column("vector", sa.LargeBinary, nullable=True),
        sa.Column("picks", sa.Text, nullable=False),
        sa.Column("answer_limit", sa.Integer, nullable=False),
        sa.Column("candidates", sa.Integer, nullable=False),
        sa.Column("complete", sa.Integer, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index(
        "ix_retrieval_agentic_answers_created_at", "retrieval_agentic_answers", ["created_at"]
    )
    op.create_index(
        "ix_retrieval_agentic_answers_library", "retrieval_agentic_answers", ["library"]
    )


def downgrade() -> None:
    op.drop_index("ix_retrieval_agentic_answers_library", table_name="retrieval_agentic_answers")
    op.drop_index("ix_retrieval_agentic_answers_created_at", table_name="retrieval_agentic_answers")
    op.drop_table("retrieval_agentic_answers")
