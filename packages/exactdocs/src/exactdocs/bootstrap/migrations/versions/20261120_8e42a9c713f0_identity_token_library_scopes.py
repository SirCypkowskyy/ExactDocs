"""Optional API token library selection; NULL preserves legacy account access.

Revision ID: 8e42a9c713f0
Revises: 3c5d9e1f7a42
"""

import sqlalchemy as sa
from alembic import op

revision = "8e42a9c713f0"
down_revision = "3c5d9e1f7a42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("identity_api_tokens", sa.Column("library_ids", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("identity_api_tokens", "library_ids")
