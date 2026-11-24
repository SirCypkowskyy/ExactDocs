"""Jobs record who queued them (#512), and the job statistics count a range of days.

``created_by_id`` is the account ID of the person whose request queued the job and
``created_by_name`` the user name it had then (kept, so a job still names its person after the
account is gone; never a token or any other secret). Both stay NULL on the rows of every job
queued before this revision: who queued those was not recorded, and nothing can tell it now.
A job no person queued (the scheduled check, a webhook, the embedding the instance queues) has
none either. ``origin`` already says whether the instance queued a job on its own (``auto``) or
not (``manual``); it is stored, not derived, so earlier jobs keep theirs.

``ingestion_jobs_created_at`` serves the day range of ``GET /stats/jobs``.

Revision ID: b7e2c4a91d58
Revises: 7f3a91c5d2e8
"""

import sqlalchemy as sa
from alembic import op

revision = "b7e2c4a91d58"
down_revision = "7f3a91c5d2e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingestion_jobs", sa.Column("created_by_id", sa.Text))
    op.add_column("ingestion_jobs", sa.Column("created_by_name", sa.Text))
    op.create_index("ingestion_jobs_created_at", "ingestion_jobs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ingestion_jobs_created_at", table_name="ingestion_jobs")
    op.drop_column("ingestion_jobs", "created_by_name")
    op.drop_column("ingestion_jobs", "created_by_id")
