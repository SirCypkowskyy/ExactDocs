"""Each library's own spend limits per UTC day and month (#102), within the instance's.

Revision ID: b8e5c3a1f9d7
Revises: d2f7b4a9c1e6
"""

import sqlalchemy as sa
from alembic import op

revision = "b8e5c3a1f9d7"
down_revision = "d2f7b4a9c1e6"
branch_labels = None
depends_on = None

_COLUMNS = ("daily_usd_micros", "monthly_usd_micros", "daily_tokens", "monthly_tokens")


def upgrade() -> None:
    for name in _COLUMNS:
        op.add_column("retrieval_library_settings", sa.Column(name, sa.BigInteger))


def downgrade() -> None:
    for name in reversed(_COLUMNS):
        op.drop_column("retrieval_library_settings", name)
