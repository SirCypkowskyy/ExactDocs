"""Chunks are stored once per content and addressed per manifest.

Revision ID: 7c2e91d4a6b8
Revises: 9b3e5a7c1d42
"""

import sqlalchemy as sa
from alembic import op

revision = "7c2e91d4a6b8"
down_revision = "9b3e5a7c1d42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retrieval_chunk_sets",
        sa.Column("blob_sha", sa.Text, primary_key=True),  # git blob SHA
        sa.Column("config_hash", sa.Text, primary_key=True),  # chunking config + parser version
        sa.Column("digest", sa.Text, nullable=False),  # fingerprint of the chunks
    )
    op.create_table(
        "retrieval_chunks",
        sa.Column("blob_sha", sa.Text, primary_key=True),
        sa.Column("config_hash", sa.Text, primary_key=True),
        sa.Column("position", sa.Integer, primary_key=True),
        sa.Column("heading_path", sa.Text, nullable=False),  # JSON list
        sa.Column("occurrence_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("anchor", sa.Text, nullable=False),
        sa.Column("code_languages", sa.Text, nullable=False),  # JSON list
        sa.ForeignKeyConstraint(
            ["blob_sha", "config_hash"],
            ["retrieval_chunk_sets.blob_sha", "retrieval_chunk_sets.config_hash"],
            ondelete="CASCADE",
        ),
    )
    # No foreign key to the catalog: manifest IDs are held by value.
    op.create_table(
        "retrieval_manifests",
        sa.Column("manifest_id", sa.Text, primary_key=True),
        sa.Column("version_id", sa.Text, nullable=False),  # `<library>/<ref>`
        sa.Column("library", sa.Text, nullable=False),
        sa.Column("indexed_at", sa.Text, nullable=False),  # ISO 8601, UTC
    )
    op.create_table(
        "retrieval_manifest_chunks",
        sa.Column(
            "manifest_id",
            sa.Text,
            sa.ForeignKey("retrieval_manifests.manifest_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("chunk_id", sa.Text, primary_key=True),
        sa.Column("article_path", sa.Text, nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("total", sa.Integer, nullable=False),
        sa.Column("prev_chunk_id", sa.Text, nullable=True),
        sa.Column("next_chunk_id", sa.Text, nullable=True),
        sa.Column("tags", sa.Text, nullable=False),  # JSON list
        sa.Column("blob_sha", sa.Text, nullable=False),
        sa.Column("config_hash", sa.Text, nullable=False),
        sa.ForeignKeyConstraint(
            ["blob_sha", "config_hash"],
            ["retrieval_chunk_sets.blob_sha", "retrieval_chunk_sets.config_hash"],
        ),
    )
    # Garbage collection asks "is this chunk set still used?"
    op.create_index(
        "ix_retrieval_manifest_chunks_set",
        "retrieval_manifest_chunks",
        ["blob_sha", "config_hash"],
    )
    # Discard and collect filter manifests by library and age.
    op.create_index(
        "ix_retrieval_manifests_library_indexed_at",
        "retrieval_manifests",
        ["library", "indexed_at"],
    )
    op.create_index("ix_retrieval_manifests_indexed_at", "retrieval_manifests", ["indexed_at"])
    # Neighbours and "all chunks of article X" (the PK is (manifest_id, chunk_id)).
    op.create_index(
        "ix_retrieval_manifest_chunks_article",
        "retrieval_manifest_chunks",
        ["manifest_id", "article_path", "position"],
    )


def downgrade() -> None:
    op.drop_table("retrieval_manifest_chunks")
    op.drop_table("retrieval_manifests")
    op.drop_table("retrieval_chunks")
    op.drop_table("retrieval_chunk_sets")
