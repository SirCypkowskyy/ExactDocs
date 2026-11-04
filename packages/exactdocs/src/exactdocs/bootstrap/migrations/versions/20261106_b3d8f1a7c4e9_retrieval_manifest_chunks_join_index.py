"""Index manifest chunk rows by the join key of a search, so many manifests cost one probe each.

Revision ID: b3d8f1a7c4e9
Revises: a1c9e4d7b352
"""

from alembic import op

revision = "b3d8f1a7c4e9"
down_revision = "a1c9e4d7b352"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_retrieval_manifest_chunks_join",
        "retrieval_manifest_chunks",
        ["blob_sha", "config_hash", "position", "manifest_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_retrieval_manifest_chunks_join", table_name="retrieval_manifest_chunks")
