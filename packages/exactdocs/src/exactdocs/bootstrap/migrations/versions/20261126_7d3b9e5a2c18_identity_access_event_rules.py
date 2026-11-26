"""Role rule changes in the access log (#577).

``identity_access_events`` gets ``rule``: a ``rule_added`` or ``rule_removed`` event's rule as
JSON, as it was when it changed (such an event's ``library`` is empty). Earlier events keep NULL.

Revision ID: 7d3b9e5a2c18
Revises: 4a7c2e9b1d63
"""

import sqlalchemy as sa
from alembic import op

revision = "7d3b9e5a2c18"
down_revision = "4a7c2e9b1d63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("identity_access_events", sa.Column("rule", sa.Text))


def downgrade() -> None:
    op.execute("DELETE FROM identity_access_events WHERE rule IS NOT NULL")
    with op.batch_alter_table("identity_access_events") as batch:
        batch.drop_column("rule")
