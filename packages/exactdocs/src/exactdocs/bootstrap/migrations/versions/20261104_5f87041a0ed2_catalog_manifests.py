"""A version is a manifest over article content shared by git blob SHA.

Revision ID: 5f87041a0ed2
Revises: 5f3a9c21d7b4
"""

import sqlalchemy as sa
from alembic import op

revision = "5f87041a0ed2"
down_revision = "5f3a9c21d7b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_article_contents",
        sa.Column("blob_sha", sa.Text, primary_key=True),  # git blob SHA
        # Opaque, raised by the importer when the same blob yields another text (parser fix).
        sa.Column("content_version", sa.Integer, primary_key=True),
        sa.Column("content", sa.Text, nullable=False),
    )
    op.create_table(
        "catalog_manifests",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column(
            "library_id",
            sa.Text,
            sa.ForeignKey("catalog_libraries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ref", sa.Text, nullable=False),  # case-sensitive, like the version's ref
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("commit_sha", sa.Text, nullable=False),
        sa.Column(
            "state",
            sa.Text,
            sa.CheckConstraint("state IN ('pending', 'active', 'superseded')"),
            nullable=False,
        ),
        sa.Column("created_at", sa.Text, nullable=False),  # ISO 8601, UTC
        sa.Column("superseded_at", sa.Text, nullable=True),  # ISO 8601, UTC
    )
    # At most one active manifest per version: the database refuses a second one.
    op.create_index(
        "ux_catalog_manifests_active",
        "catalog_manifests",
        ["library_id", "ref"],
        unique=True,
        sqlite_where=sa.text("state = 'active'"),
        postgresql_where=sa.text("state = 'active'"),
    )
    op.create_table(
        "catalog_manifest_entries",
        sa.Column(
            "manifest_id",
            sa.Text,
            sa.ForeignKey("catalog_manifests.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("path", sa.Text, primary_key=True),
        sa.Column("blob_sha", sa.Text, nullable=False),
        sa.Column("content_version", sa.Integer, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("tags", sa.Text, nullable=False),  # JSON list
        sa.Column("front_matter", sa.Text, nullable=False),  # JSON object
        sa.Column("size", sa.Integer, nullable=False),
        sa.ForeignKeyConstraint(
            ["blob_sha", "content_version"],
            ["catalog_article_contents.blob_sha", "catalog_article_contents.content_version"],
        ),
    )
    # Garbage collection asks "is this content still used?" by blob.
    op.create_index(
        "ix_catalog_manifest_entries_content",
        "catalog_manifest_entries",
        ["blob_sha", "content_version"],
    )


def downgrade() -> None:
    op.drop_table("catalog_manifest_entries")
    op.drop_table("catalog_manifests")
    op.drop_table("catalog_article_contents")
