"""On PostgreSQL, chunks are searchable through PostgreSQL full-text search.

Revision ID: 0c4e8a2f6b19
Revises: 8f2856445b87

SQLite keeps FTS5 (`retrieval_search`, 3b8f0d6e2a71); those revisions skip their FTS5 steps on
PostgreSQL, and this one creates PostgreSQL's index instead (a no-op on SQLite). One row per stored
chunk, keyed by `retrieval_chunks.id`: the foreign key removes it with its chunk, as the FTS5
trigger does. `document` is computed by PostgreSQL from the four columns FTS5 has (heading, path,
text, identifiers) with the `simple` configuration (no stemming, no stop words, like FTS5's
`unicode61`), weighted A to D. Each column first goes through `retrieval_search_words` (below), so
PostgreSQL's parser cuts words as FTS5's `tokenchars '-_.'` does. The format row records
PostgreSQL's format 1 (`retrieval.adapters.driven.postgres_fts`). A database only ever reaches this
revision through the whole history, so `retrieval_chunks` is still empty here: nothing needs
indexing.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

revision = "0c4e8a2f6b19"
down_revision = "8f2856445b87"
branch_labels = None
depends_on = None

_TEXT = sa.Text(collation="C")  # never sorted; "C" so `migrate` leaves them as they are
# The adapter's queries call this function (`retrieval.constants._PG_DOCUMENT`, `_PG_QUERY`).
# PostgreSQL's parser reads `/v1/tokens` as one file name and splits `retry_policy` at the
# underscore. FTS5 keeps `-_.` inside a word and splits at everything else: so everything else
# becomes a space, and an underscore inside a word a hyphen, which the parser keeps whole
# (`retry-policy`) and in parts. A word character is an ASCII letter or digit or any non-ASCII
# character, spelled out rather than `[[:alnum:]]`: that class follows the database's LC_CTYPE,
# and under `C` it would drop every accented, Greek or CJK word (the parser itself keeps them).
_WORDS = r"""
    CREATE FUNCTION retrieval_search_words(words text) RETURNS text
    LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
    RETURN regexp_replace(
        regexp_replace(words, '[^A-Za-z0-9_.\u0080-\U0010FFFF-]+', ' ', 'g'),
        '([A-Za-z0-9\u0080-\U0010FFFF])_(?=[A-Za-z0-9\u0080-\U0010FFFF])', '\1-', 'g')
"""
_DOCUMENT = (
    "setweight(to_tsvector('simple'::regconfig, retrieval_search_words(heading)), 'A')"
    " || setweight(to_tsvector('simple'::regconfig, retrieval_search_words(path)), 'B')"
    " || setweight(to_tsvector('simple'::regconfig, retrieval_search_words(body)), 'C')"
    " || setweight(to_tsvector('simple'::regconfig, retrieval_search_words(identifiers)), 'D')"
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(_WORDS)
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
    op.execute("DROP FUNCTION retrieval_search_words(text)")
    op.execute("UPDATE retrieval_search_format SET format = 2")
