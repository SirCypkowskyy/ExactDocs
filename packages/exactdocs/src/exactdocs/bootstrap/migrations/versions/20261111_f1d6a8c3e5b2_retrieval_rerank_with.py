"""Each library may choose whether the cross-encoder or the LLM judge reranks it (#96).

Revision ID: f1d6a8c3e5b2
Revises: d7f2a9c4e1b6
"""

import sqlalchemy as sa
from alembic import op

revision = "f1d6a8c3e5b2"
down_revision = "d7f2a9c4e1b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("retrieval_library_settings", sa.Column("rerank_with", sa.Text))


def downgrade() -> None:
    op.drop_column("retrieval_library_settings", "rerank_with")
