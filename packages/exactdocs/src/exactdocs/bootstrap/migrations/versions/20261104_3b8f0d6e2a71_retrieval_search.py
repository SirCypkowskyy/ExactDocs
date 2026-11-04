"""Chunks are searchable with BM25 through SQLite FTS5.

Revision ID: 3b8f0d6e2a71
Revises: c4d8e2f6a1b7
"""

from alembic import op

revision = "3b8f0d6e2a71"
down_revision = "c4d8e2f6a1b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `-_.` stay inside a token so `max_retries` and `--dry-run` are found whole (see
    # `identifier_tokens`). The rowid is the rowid of the chunk in `retrieval_chunks`.
    op.execute(
        """
        CREATE VIRTUAL TABLE retrieval_search USING fts5(
            heading, text, identifiers,
            tokenize = "unicode61 tokenchars '-_.'"
        )
        """
    )
    # Deleting a chunk set cascades to its chunks; their index entries go with them.
    op.execute(
        """
        CREATE TRIGGER retrieval_chunks_search_delete AFTER DELETE ON retrieval_chunks
        BEGIN
            DELETE FROM retrieval_search WHERE rowid = old.rowid;
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER retrieval_chunks_search_delete")
    op.execute("DROP TABLE retrieval_search")
