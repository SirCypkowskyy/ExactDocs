"""A chunk names the part of its section it is, apart from the section's occurrence (#141).

A section longer than the chunking's section bound is split between its top-level blocks. Its
parts share the section's heading path and occurrence index and are numbered by ``part``, so
splitting a section changes no other section's ID. Rows stored before are whole sections: 0.

Revision ID: f91e59c59169
Revises: 97095cfef767
"""

import sqlalchemy as sa
from alembic import op

revision = "f91e59c59169"
down_revision = "97095cfef767"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add ``retrieval_chunks.part``, 0 for every stored row."""
    op.add_column(
        "retrieval_chunks",
        sa.Column("part", sa.Integer, nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    """Drop ``retrieval_chunks.part``."""
    op.drop_column("retrieval_chunks", "part")
