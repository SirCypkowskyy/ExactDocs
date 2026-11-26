"""Role rules (#577): GitHub organizations, teams, groups and role values mapped to roles.

``identity_role_rules`` holds the rules admins add: a provider, a source (``github_org``,
``github_team``, ``group`` or ``role``) and its value, and a grant (``instance_admin``,
``create_libraries``, ``viewer``, ``contributor``, ``admin``) with the libraries it is given on
(a JSON array; NULL for every library that is not private). The configuration file's rules are
not stored. ``identity_account_roles`` holds each external account's role claim values, apart
from its groups so that a group never stands in for a role. ``identity_private_libraries``
names the libraries a rule for every library leaves out: those ingestion holds a token or
deploy key for, copied from ``ingestion_library_credentials`` here and kept by ingestion after.

Revision ID: 4a7c2e9b1d63
Revises: b5e8c2d4f7a1
"""

import sqlalchemy as sa
from alembic import op

revision = "4a7c2e9b1d63"
down_revision = "b5e8c2d4f7a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identity_role_rules",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("grant", sa.Text, nullable=False),
        sa.Column("libraries", sa.Text),
        sa.Column("created_by", sa.Text),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_table(
        "identity_account_roles",
        sa.Column(
            "account_id",
            sa.Text,
            sa.ForeignKey("identity_accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("name", sa.Text, primary_key=True),
    )
    op.create_table("identity_private_libraries", sa.Column("library", sa.Text, primary_key=True))
    op.execute(
        "INSERT INTO identity_private_libraries (library) "
        "SELECT DISTINCT lower(library) FROM ingestion_library_credentials"
    )


def downgrade() -> None:
    op.drop_table("identity_private_libraries")
    op.drop_table("identity_account_roles")
    op.drop_table("identity_role_rules")
