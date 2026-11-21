"""Merge the job cancellation (#432) and thinking level (#421) migrations.

Both were added on 8e42a9c713f0. Changes no schema: it only joins the two heads.

Revision ID: 6c8e3f1a5d92
Revises: 4b7d1e9c2a6f, 5b7d2e8f4c61
"""

revision = "6c8e3f1a5d92"
down_revision = ("4b7d1e9c2a6f", "5b7d2e8f4c61")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Change nothing: the branches were independent."""


def downgrade() -> None:
    """Change nothing."""
