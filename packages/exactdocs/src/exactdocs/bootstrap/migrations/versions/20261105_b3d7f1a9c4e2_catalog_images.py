"""Images the articles reference are stored once per git blob SHA, listed by manifest.

Revision ID: b3d7f1a9c4e2
Revises: b8d3f6a2c914
"""

import sqlalchemy as sa
from alembic import op

revision = "b3d7f1a9c4e2"
down_revision = "b8d3f6a2c914"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_image_blobs",
        sa.Column("blob_sha", sa.Text, primary_key=True),  # git blob SHA
        sa.Column("content_type", sa.Text, nullable=False),  # sniffed from the bytes
        sa.Column("data", sa.LargeBinary, nullable=False),
    )
    op.create_table(
        "catalog_manifest_images",
        sa.Column(
            "manifest_id",
            sa.Text,
            sa.ForeignKey("catalog_manifests.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("path", sa.Text, primary_key=True),
        sa.Column(
            "blob_sha", sa.Text, sa.ForeignKey("catalog_image_blobs.blob_sha"), nullable=False
        ),
    )
    op.create_index("ix_catalog_manifest_images_blob", "catalog_manifest_images", ["blob_sha"])


def downgrade() -> None:
    op.drop_table("catalog_manifest_images")
    op.drop_table("catalog_image_blobs")
