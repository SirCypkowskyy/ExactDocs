"""Tags users set by hand on an article path, for every version of a library.

Revision ID: c6e2a8d4f1b9
Revises: b3d7f1a9c4e2

Manifest entries keep `tags` as every tag of the article (what listings filter and count), and
gain `manual_tags` and `imported_tags`: the latter is only set while an entry has manual tags, so
removing them can bring back exactly what the import gave. Existing rows have no manual tags.
"""

import sqlalchemy as sa
from alembic import op

revision = "c6e2a8d4f1b9"
down_revision = "b3d7f1a9c4e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_manual_tags",
        sa.Column(
            "library_id",
            sa.Text,
            sa.ForeignKey("catalog_libraries.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("path", sa.Text, primary_key=True),  # an article path, of any version
        sa.Column("tags", sa.Text, nullable=False),  # JSON list, normalized, never empty
    )
    op.add_column(
        "catalog_manifest_entries",
        sa.Column("manual_tags", sa.Text, nullable=False, server_default="[]"),  # JSON list
    )
    # JSON list; NULL while the entry has no manual tags (then `tags` is what was imported).
    op.add_column("catalog_manifest_entries", sa.Column("imported_tags", sa.Text))


def downgrade() -> None:
    op.execute(
        "UPDATE catalog_manifest_entries SET tags = imported_tags WHERE imported_tags IS NOT NULL"
    )
    with op.batch_alter_table("catalog_manifest_entries") as batch:
        batch.drop_column("imported_tags")
        batch.drop_column("manual_tags")
    op.drop_table("catalog_manual_tags")
