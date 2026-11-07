"""Chunks record every heading they hold, merged ones included (#251).

A JSON list of ``[heading path, anchor, starts chunk]`` per chunk row. Rows stored before are left
NULL: their outline lists each chunk's first heading, as before. The default chunking never merges
headings, so that is every heading; any other chunking gets a new config hash, so its chunk sets
are cut again (with the records) at the library's next import or re-chunk.

Revision ID: 8f2856445b87
Revises: b2c5e8a1d7f4
"""

import sqlalchemy as sa
from alembic import op

revision = "8f2856445b87"
down_revision = "b2c5e8a1d7f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("retrieval_chunks", sa.Column("headings", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("retrieval_chunks", "headings")
