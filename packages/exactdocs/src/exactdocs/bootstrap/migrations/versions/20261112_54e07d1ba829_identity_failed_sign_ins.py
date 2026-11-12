"""The sign-in throttle's counts live in the database, shared by every process (#253).

Revision ID: 54e07d1ba829
Revises: b5e8d2a7c4f9
"""

import sqlalchemy as sa
from alembic import op

revision = "54e07d1ba829"
down_revision = "b5e8d2a7c4f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identity_failed_sign_ins",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("failures", sa.Integer, nullable=False),
        sa.Column("last_at", sa.Text, nullable=False),
        sa.Column("previous_at", sa.Text),
    )
    op.create_index("ix_identity_failed_sign_ins_last_at", "identity_failed_sign_ins", ["last_at"])
    op.create_table(
        "identity_known_sign_ins",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("signed_in_at", sa.Text, nullable=False),
    )
    op.create_index(
        "ix_identity_known_sign_ins_signed_in_at", "identity_known_sign_ins", ["signed_in_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_identity_known_sign_ins_signed_in_at", table_name="identity_known_sign_ins")
    op.drop_table("identity_known_sign_ins")
    op.drop_index("ix_identity_failed_sign_ins_last_at", table_name="identity_failed_sign_ins")
    op.drop_table("identity_failed_sign_ins")
