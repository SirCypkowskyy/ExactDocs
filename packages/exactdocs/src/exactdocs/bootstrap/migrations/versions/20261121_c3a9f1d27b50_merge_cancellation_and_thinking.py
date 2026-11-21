"""Join the job cancellation (#432) and thinking level (#421) migrations.

Both were written against ``8e42a9c713f0`` and merged to ``develop`` one after the other, which
left two heads. This one changes no schema.

Revision ID: c3a9f1d27b50
Revises: 4b7d1e9c2a6f, 5b7d2e8f4c61
"""

revision = "c3a9f1d27b50"
down_revision = ("4b7d1e9c2a6f", "5b7d2e8f4c61")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Change nothing: the two branches touch different tables."""


def downgrade() -> None:
    """Change nothing."""
