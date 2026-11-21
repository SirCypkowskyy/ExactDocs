"""Jobs can be cancelled (#432): the ``cancelled`` state, and who cancelled a job and when.

The ``state`` CHECK constraint gains ``cancelled``. It was created unnamed with the table: on
PostgreSQL it is ``ingestion_jobs_state_check`` (the server's own name), on SQLite the table is
recreated (batch) with the new constraint, named alike, in place of the unnamed one.

Revision ID: 4b7d1e9c2a6f
Revises: 8e42a9c713f0
"""

import warnings

import sqlalchemy as sa
from alembic import op

revision = "4b7d1e9c2a6f"
down_revision = "8e42a9c713f0"
branch_labels = None
depends_on = None

_CHECK = "ingestion_jobs_state_check"
_STATES = "state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')"
_OLD_STATES = "state IN ('queued', 'running', 'succeeded', 'failed')"


def _replace_check(condition: str) -> None:
    """Replace the CHECK constraint of ``state`` with one on ``condition``.

    Args:
        condition: The new constraint's SQL condition.
    """
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint(_CHECK, "ingestion_jobs", type_="check")
        op.create_check_constraint(_CHECK, "ingestion_jobs", condition)
        return
    # Alembic leaves the reflected unnamed constraint out of the recreated table, and says so;
    # the named one below replaces it (a named one is reflected and dropped by its name).
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", "Unnamed CHECK constraint", UserWarning)
        named = {
            c["name"] for c in sa.inspect(op.get_bind()).get_check_constraints("ingestion_jobs")
        }
        with op.batch_alter_table("ingestion_jobs", recreate="always") as batch:
            if _CHECK in named:
                batch.drop_constraint(_CHECK, type_="check")
            batch.create_check_constraint(_CHECK, condition)


def upgrade() -> None:
    op.add_column("ingestion_jobs", sa.Column("cancelled_by", sa.Text))
    op.add_column("ingestion_jobs", sa.Column("cancelled_at", sa.Text))
    _replace_check(_STATES)


def downgrade() -> None:
    # An older release knows no `cancelled` state: those jobs read as failed, with the reason.
    op.execute(
        "UPDATE ingestion_jobs SET state = 'failed', error = 'cancelled', error_code = 'cancelled'"
        " WHERE state = 'cancelled'"
    )
    _replace_check(_OLD_STATES)
    # A running job flagged for cancellation just runs on under the older release.
    op.drop_column("ingestion_jobs", "cancelled_at")
    op.drop_column("ingestion_jobs", "cancelled_by")
