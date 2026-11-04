"""A section's own heading and its ancestors are indexed apart, so a definition beats its children.

Revision ID: a91c4e7b3d02
Revises: d7e2a4b9c150

Before, one `heading` column held the whole path, so `Docker > Troubleshooting` matched `docker`
about as well as the `Docker` section itself. FTS5 tables cannot gain a column, so the table is
rebuilt and refilled in Python (`identifier_tokens` cannot be computed in SQL).
"""

import json
from collections.abc import Callable

import sqlalchemy as sa
from alembic import op

from exactdocs.retrieval.models import identifier_tokens

revision = "a91c4e7b3d02"
down_revision = "d7e2a4b9c150"
branch_labels = None
depends_on = None

_Row = Callable[[int, list[str], str], dict[str, object]]


def _rebuild(create: str, insert: str, row: _Row) -> None:
    """Recreate the full-text table (the chunk delete trigger stays) and refill it."""
    op.execute("DROP TABLE retrieval_search")
    op.execute(create)
    connection = op.get_bind()
    existing = connection.execute(
        sa.text("SELECT id, heading_path, content FROM retrieval_chunks")
    ).yield_per(500)
    for batch in existing.partitions():
        connection.execute(
            sa.text(insert), [row(r.id, json.loads(r.heading_path), r.content) for r in batch]
        )


def _before(rowid: int, heading_path: list[str], content: str) -> dict[str, object]:
    heading = " / ".join(heading_path)
    return {
        "rowid": rowid,
        "heading": heading,
        "text": content,
        "identifiers": identifier_tokens(f"{heading}\n{content}"),
    }


def _after(rowid: int, heading_path: list[str], content: str) -> dict[str, object]:
    """The row as this revision shapes it: own heading, ancestors, text, identifiers (frozen)."""
    full = " / ".join(heading_path)
    return {
        "rowid": rowid,
        "heading": heading_path[-1] if heading_path else "",
        "path": " / ".join(heading_path[:-1]),
        "text": content,
        "identifiers": identifier_tokens(f"{full}\n{content}"),
    }


def upgrade() -> None:
    _rebuild(
        """
        CREATE VIRTUAL TABLE retrieval_search USING fts5(
            heading, path, text, identifiers,
            tokenize = "unicode61 tokenchars '-_.'"
        )
        """,
        "INSERT INTO retrieval_search (rowid, heading, path, text, identifiers) "
        "VALUES (:rowid, :heading, :path, :text, :identifiers)",
        _after,
    )


def downgrade() -> None:
    _rebuild(
        """
        CREATE VIRTUAL TABLE retrieval_search USING fts5(
            heading, text, identifiers,
            tokenize = "unicode61 tokenchars '-_.'"
        )
        """,
        "INSERT INTO retrieval_search (rowid, heading, text, identifiers) "
        "VALUES (:rowid, :heading, :text, :identifiers)",
        _before,
    )
