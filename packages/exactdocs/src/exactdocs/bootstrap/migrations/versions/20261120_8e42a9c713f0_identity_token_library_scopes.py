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
    scoped = (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM identity_api_tokens WHERE library_ids IS NOT NULL LIMIT 1"))
        .first()
    )
    if scoped is not None:
        message = (
            "Revoke scoped API tokens before downgrading; "
            "removing library scopes would widen their access."
        )
        raise RuntimeError(message)
    op.drop_column("identity_api_tokens", "library_ids")
