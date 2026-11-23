"""Access log (ACL-05, #112): who changed which library's access, how and when.

``identity_access_events`` is append-only: one row per creation, grant, revocation, ownership
transfer or deletion of a library. ``id`` is a UUIDv7, so it sorts in the order the events were
recorded; ``actor`` is an account ID, or NULL when the instance itself made the change (the
command line, a job). No foreign key: the log outlives the libraries it names. A deletion has no
``kind``, ``subject`` or ``role``. Nothing that happened before this revision is in the log.

Revision ID: 9d4f2b7e1c83
Revises: c3a9f1d27b50
"""

import sqlalchemy as sa
from alembic import op

revision = "9d4f2b7e1c83"
down_revision = "c3a9f1d27b50"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identity_access_events",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("library", sa.Text, nullable=False),
        sa.Column("at", sa.Text, nullable=False),
        sa.Column("actor", sa.Text),
        sa.Column("change", sa.Text, nullable=False),
        sa.Column("kind", sa.Text),
        sa.Column("subject", sa.Text),
        sa.Column("role", sa.Text),
        sa.Column("previous_role", sa.Text),
    )
    op.create_index("identity_access_events_library", "identity_access_events", ["library", "id"])


def downgrade() -> None:
    op.drop_index("identity_access_events_library", table_name="identity_access_events")
    op.drop_table("identity_access_events")
