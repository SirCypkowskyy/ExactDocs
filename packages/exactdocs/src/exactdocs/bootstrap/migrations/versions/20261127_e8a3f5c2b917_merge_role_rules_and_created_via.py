"""Join the two revisions that both followed the role rules tables (#577, #613).

``7d3b9e5a2c18`` (rule events in the access log) and ``c4d1a8e93f20`` (how a job was created)
were merged into develop at the same time on the same parent, ``4a7c2e9b1d63``. They touch
different tables, so this revision only makes the history one line again. Nothing changes.

Revision ID: e8a3f5c2b917
Revises: 7d3b9e5a2c18, c4d1a8e93f20
"""

revision = "e8a3f5c2b917"
down_revision = ("7d3b9e5a2c18", "c4d1a8e93f20")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
