"""Each library may choose whether the cross-encoder or the LLM judge reranks it (#96).

Revision ID: f1d6a8c3e5b2
Revises: c3a9e7d1f4b8
"""

import sqlalchemy as sa
from alembic import op

revision = "f1d6a8c3e5b2"
down_revision = "c3a9e7d1f4b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("retrieval_library_settings", sa.Column("rerank_with", sa.Text))


def downgrade() -> None:
    op.drop_column("retrieval_library_settings", "rerank_with")
