"""Each library's project logo (#504): one row per library, deleted with it.

The importer finds the logo in the default version (the README's logo image or a conventional
file), checks or cleans it and the catalog keeps it here, so it is served from ExactDocs' own
origin. ``digest`` names the bytes (the library DTOs' ``logo`` and the ``ETag``); ``path`` and
``ref`` say where it was found. A new table only, so the revision can follow any other one: when
two branches add a revision on the same head, re-point ``down_revision`` (or add a merge).

Revision ID: 6a1e4c9b2d75
Revises: 9d4f2b7e1c83
"""

import sqlalchemy as sa
from alembic import op

revision = "6a1e4c9b2d75"
down_revision = "9d4f2b7e1c83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_library_logos",
        sa.Column(
            "library_id",
            sa.Text,
            sa.ForeignKey("catalog_libraries.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("digest", sa.Text, nullable=False),
        sa.Column("content_type", sa.Text, nullable=False),
        sa.Column("data", sa.LargeBinary, nullable=False),
        sa.Column("path", sa.Text, nullable=False),  # repository-relative, untrusted text
        sa.Column("ref", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("catalog_library_logos")
