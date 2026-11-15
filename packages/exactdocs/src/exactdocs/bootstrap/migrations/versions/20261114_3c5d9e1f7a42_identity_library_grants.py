"""Library roles (ACL-02, #108): who holds which role on which library.

``identity_library_grants`` has one row per (library, kind, subject): ``kind`` is ``user``
(``subject`` is an account ID) or ``group`` (a group name as stored in
``identity_account_groups``), ``role`` one of ``viewer``, ``contributor``, ``admin``,
``creator``. Libraries that exist already get no row: an operator (account role ``admin``)
manages them and shares them from there.

Revision ID: 3c5d9e1f7a42
Revises: b7e4c1a9d305
"""

import sqlalchemy as sa
from alembic import op

revision = "3c5d9e1f7a42"
down_revision = "b7e4c1a9d305"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identity_library_grants",
        sa.Column("library", sa.Text, primary_key=True),
        sa.Column("kind", sa.Text, primary_key=True),
        sa.Column("subject", sa.Text, primary_key=True),
        sa.Column("role", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("identity_library_grants")
