"""An account's last activity (#515), kept to the hour; NULL until its next sign-in or request.

Revision ID: b5e8c2d4f7a1
Revises: 19725bf1e467
"""

import sqlalchemy as sa
from alembic import op

revision = "b5e8c2d4f7a1"
down_revision = "19725bf1e467"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("identity_accounts", sa.Column("last_active_at", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("identity_accounts", "last_active_at")
