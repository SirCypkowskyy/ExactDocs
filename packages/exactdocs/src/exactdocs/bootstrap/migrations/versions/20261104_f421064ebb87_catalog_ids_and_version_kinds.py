"""Libraries get context7-style IDs, metadata and settings; versions get a kind and a commit.

The first catalog tables only held names, and nothing was ever released with them, so they are
replaced rather than altered.

Revision ID: f421064ebb87
Revises: ac89e0a428cd
"""

import sqlalchemy as sa
from alembic import op

revision = "f421064ebb87"
down_revision = "ac89e0a428cd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("catalog_library_versions")
    op.drop_table("catalog_libraries")
    op.create_table(
        "catalog_libraries",
        sa.Column("id", sa.Text, primary_key=True),  # `/owner/repo`, lower-case
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("host", sa.Text, nullable=False),
        sa.Column("default_branch", sa.Text, nullable=True),
        sa.Column("pinned_version", sa.Text, nullable=True),  # LIB-10 (MVP-2); not read yet
        sa.Column("settings", sa.Text, nullable=False),  # JSON
    )
    op.create_table(
        "catalog_library_versions",
        sa.Column(
            "library_id",
            sa.Text,
            sa.ForeignKey("catalog_libraries.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("ref", sa.Text, primary_key=True),  # case-sensitive (SQLite BINARY collation)
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("commit_sha", sa.Text, nullable=False),
        sa.Column("imported_at", sa.Text, nullable=False),  # ISO 8601, UTC
    )


def downgrade() -> None:
    op.drop_table("catalog_library_versions")
    op.drop_table("catalog_libraries")
    op.create_table("catalog_libraries", sa.Column("name", sa.Text, primary_key=True))
    op.create_table(
        "catalog_library_versions",
        sa.Column(
            "library_name",
            sa.Text,
            sa.ForeignKey("catalog_libraries.name", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.Text, primary_key=True),
    )
