"""Index retrieval chunk rows by chunk ID, so a chunk is found without knowing its manifest.

Revision ID: e7a4b1c9d2f6
Revises: c3a8e1f94b27
"""

from alembic import op

revision = "e7a4b1c9d2f6"
down_revision = "c3a8e1f94b27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_retrieval_manifest_chunks_chunk_id", "retrieval_manifest_chunks", ["chunk_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_retrieval_manifest_chunks_chunk_id", table_name="retrieval_manifest_chunks")
