"""A version records who asked for it: a person (``manual``) or the scheduled check (``auto``).

The manifest carries the origin its import was queued with; activating the first manifest of a
version gives the version that origin, and later manifests never change it. Existing rows were
all added by hand.

Revision ID: e3b7c1d9a4f2
Revises: c7e3a9d1f5b2
"""

import sqlalchemy as sa
from alembic import op

revision = "e3b7c1d9a4f2"
down_revision = "c7e3a9d1f5b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("catalog_library_versions", "catalog_manifests"):
        op.add_column(table, sa.Column("origin", sa.Text, nullable=False, server_default="manual"))


def downgrade() -> None:
    for table in ("catalog_manifests", "catalog_library_versions"):
        op.drop_column(table, "origin")
