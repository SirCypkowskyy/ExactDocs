"""Each library may set how many of its best candidates the reranker reorders (#93).

Revision ID: 5abe3b929c5f
Revises: e4b8d2f6a9c1
"""

import sqlalchemy as sa
from alembic import op

revision = "5abe3b929c5f"
down_revision = "e4b8d2f6a9c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("retrieval_library_settings", sa.Column("rerank_top_n", sa.Integer))


def downgrade() -> None:
    op.drop_column("retrieval_library_settings", "rerank_top_n")
