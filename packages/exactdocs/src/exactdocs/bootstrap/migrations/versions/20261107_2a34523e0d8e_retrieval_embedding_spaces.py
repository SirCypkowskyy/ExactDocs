"""Embedding spaces of the vector store (RET-01): one row per model and input format.

Each space keeps its vectors in a table of its own, `retrieval_vec_<id>`, which the vector index
adapter creates when the space is created and drops when it is retired (like the search index
tables of `exactdocs reindex`), so no revision lists them. Their rows reference
`retrieval_chunks.id` with ON DELETE CASCADE: a revision that rebuilds `retrieval_chunks` must
keep its IDs, or rebuild those tables too.

Revision ID: 2a34523e0d8e
Revises: a7c3e9b1d5f2
"""

import sqlalchemy as sa
from alembic import op

revision = "2a34523e0d8e"
down_revision = "a7c3e9b1d5f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retrieval_embedding_spaces",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("profile_kind", sa.Text, nullable=False),  # provider profile kind
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("dimensions", sa.Integer, nullable=False),
        sa.Column("metric", sa.Text, nullable=False),  # VectorMetric value
        sa.Column("input_format", sa.Integer, nullable=False),  # EMBEDDING_INPUT_FORMAT
        sa.Column("state", sa.Text, nullable=False),  # building, active, retired
        sa.Column("created_at", sa.Text, nullable=False),  # ISO 8601, UTC
        sa.Column("activated_at", sa.Text),
        sqlite_autoincrement=True,  # an ID, and so a table name, is never reused
    )


def downgrade() -> None:
    connection = op.get_bind()
    for (space_id,) in connection.execute(sa.text("SELECT id FROM retrieval_embedding_spaces")):
        op.execute(f"DROP TABLE IF EXISTS retrieval_vec_{int(space_id)}")
    op.drop_table("retrieval_embedding_spaces")
