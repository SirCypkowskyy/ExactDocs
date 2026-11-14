"""Push webhooks (TEAM-03): a sealed secret per library, the deliveries seen, one queued push.

``ingestion_webhooks`` keeps one secret per library, sealed with the instance's key under its own
purpose. ``ingestion_webhook_deliveries`` remembers each delivery for a week, so a redelivery
is answered ``duplicate``; its primary key makes the insert the check, atomically on
PostgreSQL. The partial unique index ``ingestion_jobs_queued_push`` keeps one queued ``push``
job per (library, ref, ref kind), so a burst of pushes coalesces into one job.

Revision ID: bc0d89570be4
Revises: 767adfc01f8a
"""

import sqlalchemy as sa
from alembic import op

revision = "bc0d89570be4"
down_revision = "767adfc01f8a"
branch_labels = None
depends_on = None

# Must match ``exactdocs.ingestion.constants.QUEUED_PUSH_SQL`` byte for byte (SQLite uses a
# partial index only for a condition spelled exactly like it); a revision is frozen, so it spells
# the literal rather than importing the constant, which may change later.
QUEUED_PUSH = "state = 'queued' AND kind = 'push'"


def upgrade() -> None:
    op.create_table(
        "ingestion_webhooks",
        sa.Column("library", sa.Text, primary_key=True),
        sa.Column("sealed", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_table(
        "ingestion_webhook_deliveries",
        sa.Column("library", sa.Text, primary_key=True),
        sa.Column("provider", sa.Text, primary_key=True),
        sa.Column("delivery_id", sa.Text, primary_key=True),
        sa.Column("received_at", sa.Text, nullable=False),
    )
    op.create_index(
        "ingestion_webhook_deliveries_received_at",
        "ingestion_webhook_deliveries",
        ["received_at"],
    )
    op.create_index(
        "ingestion_jobs_queued_push",
        "ingestion_jobs",
        ["library", "version", "ref_kind"],
        unique=True,
        sqlite_where=sa.text(QUEUED_PUSH),
        postgresql_where=sa.text(QUEUED_PUSH),
    )


def downgrade() -> None:
    op.drop_index("ingestion_jobs_queued_push", table_name="ingestion_jobs")
    op.drop_table("ingestion_webhook_deliveries")
    op.drop_table("ingestion_webhooks")
