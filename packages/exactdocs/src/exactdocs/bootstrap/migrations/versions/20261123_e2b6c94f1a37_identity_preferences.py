"""Interface preferences (#487): how each account wants the interface to look and behave.

``identity_preferences`` holds one row per account that saved its preferences, as one JSON
object (theme, contrast, text size and spacing, motion, font, link underlines, target size,
language, library logos), so a preference added later needs no revision: a key a row lacks reads
as its default. An account without a row never saved any. The row goes with its account.

Revision ID: e2b6c94f1a37
Revises: 9d4f2b7e1c83
"""

import sqlalchemy as sa
from alembic import op

revision = "e2b6c94f1a37"
down_revision = "9d4f2b7e1c83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identity_preferences",
        sa.Column(
            "account_id",
            sa.Text,
            sa.ForeignKey("identity_accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("preferences", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("identity_preferences")
