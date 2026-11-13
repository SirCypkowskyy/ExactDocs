"""A library's unfinished jobs are indexed apart from its history (#329).

Telling whether a ref is busy reads ``library = :l AND state IN ('queued', 'running') ORDER BY
id DESC``. Neither ``(library, id)`` (every job of the library) nor ``state`` (every library's
unfinished jobs, then a sort) serves it alone; this partial index holds only unfinished rows,
so the query reads those and nothing else, already in ID order.

Revision ID: 97095cfef767
Revises: 3d8919f935dd
"""

import sqlalchemy as sa
from alembic import op

revision = "97095cfef767"
down_revision = "3d8919f935dd"
branch_labels = None
depends_on = None

UNFINISHED = "state IN ('queued', 'running')"


def upgrade() -> None:
    op.create_index(
        "ingestion_jobs_unfinished",
        "ingestion_jobs",
        ["library", "id"],
        sqlite_where=sa.text(UNFINISHED),
        postgresql_where=sa.text(UNFINISHED),
    )


def downgrade() -> None:
    op.drop_index("ingestion_jobs_unfinished", table_name="ingestion_jobs")
