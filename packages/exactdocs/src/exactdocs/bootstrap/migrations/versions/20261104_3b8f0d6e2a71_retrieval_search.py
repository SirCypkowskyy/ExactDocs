"""Chunks are searchable with BM25 through SQLite FTS5.

Revision ID: 3b8f0d6e2a71
Revises: c4d8e2f6a1b7

`retrieval_chunks` gets an explicit `id INTEGER PRIMARY KEY` (the table is rebuilt and its rows
copied): the full-text table is keyed by it, and an implicit rowid may change when the table is
vacuumed or rebuilt. Chunks that already exist are indexed here, in Python, because
`identifier_tokens` cannot be computed in SQL.
"""

import json

import sqlalchemy as sa
from alembic import op

from exactdocs.retrieval.adapters.driven.sqlite_fts import fts_row

revision = "3b8f0d6e2a71"
down_revision = "c4d8e2f6a1b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Foreign keys are off while revisions run (bootstrap.database.migrate) and nothing
    # references retrieval_chunks, so the old table can simply be replaced.
    op.rename_table("retrieval_chunks", "retrieval_chunks_old")
    op.create_table(
        "retrieval_chunks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("blob_sha", sa.Text, nullable=False),
        sa.Column("config_hash", sa.Text, nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("heading_path", sa.Text, nullable=False),  # JSON list
        sa.Column("occurrence_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("anchor", sa.Text, nullable=False),
        sa.Column("code_languages", sa.Text, nullable=False),  # JSON list
        sa.ForeignKeyConstraint(
            ["blob_sha", "config_hash"],
            ["retrieval_chunk_sets.blob_sha", "retrieval_chunk_sets.config_hash"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("blob_sha", "config_hash", "position"),
    )
    op.execute(
        """
        INSERT INTO retrieval_chunks (blob_sha, config_hash, position, heading_path,
            occurrence_index, content, content_hash, anchor, code_languages)
        SELECT blob_sha, config_hash, position, heading_path, occurrence_index, content,
            content_hash, anchor, code_languages
        FROM retrieval_chunks_old ORDER BY blob_sha, config_hash, position
        """
    )
    op.drop_table("retrieval_chunks_old")

    # `-_.` stay inside a token so `max_retries` and `--dry-run` are found whole (see
    # `identifier_tokens`). The rowid is `retrieval_chunks.id`.
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
            DELETE FROM retrieval_search WHERE rowid = old.id;
        END
        """
    )
    connection = op.get_bind()
    existing = connection.execute(
        sa.text("SELECT id, heading_path, content FROM retrieval_chunks")
    ).yield_per(500)
    for batch in existing.partitions():
        connection.execute(
            sa.text(
                "INSERT INTO retrieval_search (rowid, heading, text, identifiers) "
                "VALUES (:rowid, :heading, :text, :identifiers)"
            ),
            [fts_row(r.id, json.loads(r.heading_path), r.content) for r in batch],
        )


def downgrade() -> None:
    op.execute("DROP TRIGGER retrieval_chunks_search_delete")
    op.execute("DROP TABLE retrieval_search")
    # The id column stays: it is harmless and rebuilding the table again buys nothing.
