"""On PostgreSQL, chunks are searchable through PostgreSQL full-text search.

Revision ID: 0c4e8a2f6b19
Revises: b2c5e8a1d7f4

SQLite keeps FTS5 (`retrieval_search`, 3b8f0d6e2a71); those revisions skip their FTS5 steps on
PostgreSQL, and this one creates PostgreSQL's index instead (a no-op on SQLite). One row per stored
chunk, keyed by `retrieval_chunks.id`: the foreign key removes it with its chunk, as the FTS5
trigger does. `document` is computed by PostgreSQL from the four columns FTS5 has (heading, path,
text, identifiers) with the `simple` configuration (no stemming, no stop words, like FTS5's
`unicode61`), weighted A to D. The format row records PostgreSQL's format 1
(`retrieval.adapters.driven.postgres_fts`). A database only ever reaches this revision through the
whole history, so `retrieval_chunks` is still empty here: nothing needs indexing.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

revision = "0c4e8a2f6b19"
down_revision = "b2c5e8a1d7f4"
branch_labels = None
depends_on = None

_TEXT = sa.Text(collation="C")  # never sorted; "C" so `migrate` leaves them as they are
_DOCUMENT = (
    "setweight(to_tsvector('simple'::regconfig, heading), 'A')"
    " || setweight(to_tsvector('simple'::regconfig, path), 'B')"
    " || setweight(to_tsvector('simple'::regconfig, body), 'C')"
    " || setweight(to_tsvector('simple'::regconfig, identifiers), 'D')"
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.create_table(
        "retrieval_search",
        sa.Column(
            "chunk_id",
            sa.Integer,
            sa.ForeignKey("retrieval_chunks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("heading", _TEXT, nullable=False),
        sa.Column("path", _TEXT, nullable=False),
        sa.Column("body", _TEXT, nullable=False),
        sa.Column("identifiers", _TEXT, nullable=False),
        sa.Column("document", TSVECTOR, sa.Computed(_DOCUMENT, persisted=True)),
    )
    op.create_index(
        "ix_retrieval_search_document",
        "retrieval_search",
        ["document"],
        postgresql_using="gin",
    )
    op.execute("UPDATE retrieval_search_format SET format = 1")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.drop_table("retrieval_search")
    op.execute("UPDATE retrieval_search_format SET format = 2")
