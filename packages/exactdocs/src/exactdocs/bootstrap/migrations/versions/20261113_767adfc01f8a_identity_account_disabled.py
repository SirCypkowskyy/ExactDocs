"""An operator can disable a local account (ACL-06): record when, NULL while it may sign in.

Revision ID: 767adfc01f8a
Revises: e613cf99773e
"""

import sqlalchemy as sa
from alembic import op

revision = "767adfc01f8a"
down_revision = "e613cf99773e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("identity_accounts", sa.Column("disabled_at", sa.Text))


def downgrade() -> None:
    op.drop_column("identity_accounts", "disabled_at")
