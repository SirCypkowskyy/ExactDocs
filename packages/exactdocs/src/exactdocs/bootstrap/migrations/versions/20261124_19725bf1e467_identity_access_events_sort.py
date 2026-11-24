"""Access log sort and filters (#514): indexes for its time order, by library, actor and subject.

Both access logs are newest first by default, now by ``at`` (ties by ``id``) rather than by
``id`` alone, and filter by actor, subject and a time range. ``(at, id)`` serves the instance's
log and its date bounds; ``(library, at, id)``, ``(actor, at, id)`` and ``(subject, at, id)``
serve a library's log and the actor and subject filters in that order. The ``(library, id)``
index stays: it serves the sort by library and a library's events since its last removal.

Revision ID: 19725bf1e467
Revises: b7e2c4a91d58
"""

from alembic import op

revision = "19725bf1e467"
down_revision = "b7e2c4a91d58"
branch_labels = None
depends_on = None

_TABLE = "identity_access_events"
_INDEXES = {
    "identity_access_events_at": ["at", "id"],
    "identity_access_events_library_at": ["library", "at", "id"],
    "identity_access_events_actor": ["actor", "at", "id"],
    "identity_access_events_subject": ["subject", "at", "id"],
}


def upgrade() -> None:
    for name, columns in _INDEXES.items():
        op.create_index(name, _TABLE, columns)


def downgrade() -> None:
    for name in reversed(_INDEXES):
        op.drop_index(name, table_name=_TABLE)
