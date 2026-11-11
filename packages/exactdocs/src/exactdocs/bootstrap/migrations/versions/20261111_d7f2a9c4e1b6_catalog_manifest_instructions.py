"""The commit's AGENTS.md / CLAUDE.md files kept with a manifest for agentic retrieval (#101).

Revision ID: d7f2a9c4e1b6
Revises: c3a9e7d1f4b8
"""

import sqlalchemy as sa
from alembic import op

revision = "d7f2a9c4e1b6"
down_revision = "c3a9e7d1f4b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_manifest_instructions",
        sa.Column(
            "manifest_id",
            sa.Text,
            sa.ForeignKey("catalog_manifests.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("path", sa.Text, primary_key=True),  # repository-relative, e.g. AGENTS.md
        sa.Column("content", sa.Text, nullable=False),  # untrusted repository text
    )
    # A library's repo guidance (RET-08): off (keep nothing), notes (user-channel notes) or
    # trusted (the root file also becomes system instructions).
    op.add_column(
        "retrieval_library_settings",
        sa.Column("repo_guidance", sa.Text, nullable=False, server_default="off"),
    )


def downgrade() -> None:
    op.drop_column("retrieval_library_settings", "repo_guidance")
    op.drop_table("catalog_manifest_instructions")
