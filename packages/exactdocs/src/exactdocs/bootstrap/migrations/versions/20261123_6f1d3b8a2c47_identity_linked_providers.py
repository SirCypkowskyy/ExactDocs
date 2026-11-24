"""Linked sign-in providers (#506): an account may hold one identity of each provider.

``identity_external_identities`` loses its unique ``account_id``: an account keeps the identity it
was created through (its *origin*, ``linked_at`` NULL) and may link one identity of every other
provider from Account settings (``linked_at`` set). Two unique indexes replace the constraint: one
identity per (account, provider), and one origin per account. ``identity_sign_in_attempts`` gains
``link_session_hash``: a link's callback must come back with the session that started it.

The unique ``account_id`` was created unnamed with the table: on PostgreSQL it is
``identity_external_identities_account_id_key`` (the server's own name); on SQLite the table is
recreated (batch), the reflected constraint named by a naming convention so it can be dropped.

Revision ID: 6f1d3b8a2c47
Revises: 6a1e4c9b2d75
"""

import sqlalchemy as sa
from alembic import op

revision = "6f1d3b8a2c47"
down_revision = "6a1e4c9b2d75"
branch_labels = None
depends_on = None

_TABLE = "identity_external_identities"
_UNIQUE = "identity_external_identities_account_id_key"
_PROVIDER = "identity_external_identities_account_provider"
_ORIGIN = "identity_external_identities_origin"
_NAMING = {"uq": "%(table_name)s_%(column_0_name)s_key"}


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(_TABLE, recreate="always", naming_convention=_NAMING) as batch:
            batch.drop_constraint(_UNIQUE, type_="unique")
            batch.add_column(sa.Column("linked_at", sa.Text))
    else:
        op.drop_constraint(_UNIQUE, _TABLE, type_="unique")
        op.add_column(_TABLE, sa.Column("linked_at", sa.Text))
    op.create_index(_PROVIDER, _TABLE, ["account_id", "provider"], unique=True)
    origin = sa.text("linked_at IS NULL")
    op.create_index(
        _ORIGIN, _TABLE, ["account_id"], unique=True, sqlite_where=origin, postgresql_where=origin
    )
    op.add_column("identity_sign_in_attempts", sa.Column("link_session_hash", sa.Text))


def downgrade() -> None:
    # An older release knows one identity per account and no links: the linked identities and
    # the links still waiting for their callback go (the accounts keep their origins).
    op.execute("DELETE FROM identity_sign_in_attempts WHERE link_session_hash IS NOT NULL")
    op.drop_column("identity_sign_in_attempts", "link_session_hash")
    op.execute("DELETE FROM identity_external_identities WHERE linked_at IS NOT NULL")
    op.drop_index(_ORIGIN, table_name=_TABLE)
    op.drop_index(_PROVIDER, table_name=_TABLE)
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(_TABLE, recreate="always") as batch:
            batch.drop_column("linked_at")
            batch.create_unique_constraint(_UNIQUE, ["account_id"])
    else:
        op.drop_column(_TABLE, "linked_at")
        op.create_unique_constraint(_UNIQUE, _TABLE, ["account_id"])
