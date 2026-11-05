"""The search index records the format it was built in, so a release can ask for a reindex.

Revision ID: d4f8b2c6e9a3
Revises: b3d7f1a9c4e2

One row: the format of `retrieval_search` (see `FORMAT` in the FTS5 adapter). Format 1 was the
single heading column of 3b8f0d6e2a71; a91c4e7b3d02 rebuilt the table as format 2 (own heading
and ancestors apart), which every database at this revision holds.
"""

import sqlalchemy as sa
from alembic import op

revision = "d4f8b2c6e9a3"
down_revision = "b3d7f1a9c4e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retrieval_search_format",
        sa.Column("id", sa.Integer, sa.CheckConstraint("id = 1"), primary_key=True),
        sa.Column("format", sa.Integer, nullable=False),
    )
    # 2, frozen: the format a91c4e7b3d02 built, not the adapter's current value
    op.execute("INSERT INTO retrieval_search_format (id, format) VALUES (1, 2)")


def downgrade() -> None:
    # A rebuild may have left `retrieval_search_next` and its trigger behind; they go too.
    op.execute("DROP TRIGGER IF EXISTS retrieval_chunks_search_next_delete")
    op.execute("DROP TABLE IF EXISTS retrieval_search_next")
    op.drop_table("retrieval_search_format")
