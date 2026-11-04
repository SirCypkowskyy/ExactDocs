"""Files git saw moved between versions, stored with the manifest of the newer one.

Revision ID: b8d3f6a2c914
Revises: a1c9e4d7b352
"""

import sqlalchemy as sa
from alembic import op

revision = "b8d3f6a2c914"
down_revision = "a1c9e4d7b352"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_manifest_renames",
        sa.Column(
            "manifest_id",
            sa.Text,
            sa.ForeignKey("catalog_manifests.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        # The path in the version `from_ref` (an earlier one); a path is renamed once per manifest.
        sa.Column("old_path", sa.Text, primary_key=True),
        sa.Column("from_ref", sa.Text, nullable=False),
        sa.Column("new_path", sa.Text, nullable=False),  # an article of the manifest
        sa.Column(
            "similarity",
            sa.Integer,
            sa.CheckConstraint("similarity BETWEEN 1 AND 100"),
            nullable=False,
        ),
    )
    # "Which file did this one come from?" (the reverse lookup); the primary key serves old paths.
    op.create_index(
        "ix_catalog_manifest_renames_new", "catalog_manifest_renames", ["manifest_id", "new_path"]
    )


def downgrade() -> None:
    op.drop_table("catalog_manifest_renames")
