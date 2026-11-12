"""A library's jobs are indexed by ID, so a page of them is a range read (#149).

The job list pages with ``library = :l AND id < :before ORDER BY id DESC LIMIT :n``. The old
``(library, created_at)`` index served no query that ``(library, id)`` does not serve as well:
the queries that order by ``created_at`` filter by state, not by library.

Revision ID: 3d8919f935dd
Revises: 54e07d1ba829
"""

from alembic import op

revision = "3d8919f935dd"
down_revision = "54e07d1ba829"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ingestion_jobs_library_id", "ingestion_jobs", ["library", "id"])
    op.drop_index("ingestion_jobs_library", table_name="ingestion_jobs")


def downgrade() -> None:
    op.create_index("ingestion_jobs_library", "ingestion_jobs", ["library", "created_at"])
    op.drop_index("ingestion_jobs_library_id", table_name="ingestion_jobs")
