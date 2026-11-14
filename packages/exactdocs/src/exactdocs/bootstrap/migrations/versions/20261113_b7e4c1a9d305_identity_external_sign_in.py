"""External sign-in through OIDC (ACL-01, #105): linked identities, groups and sign-in attempts.

An account an identity provider creates has no password, so ``identity_accounts.password_hash``
may be NULL. ``identity_external_identities`` links an (issuer, subject) to one account, with its
sealed refresh token and when its access ends; ``identity_account_groups`` holds each account's
groups at its provider; ``identity_sign_in_attempts`` keeps a started sign-in until its callback.

Revision ID: b7e4c1a9d305
Revises: bc0d89570be4
"""

import sqlalchemy as sa
from alembic import op

revision = "b7e4c1a9d305"
down_revision = "bc0d89570be4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("identity_accounts") as batch:
        batch.alter_column("password_hash", existing_type=sa.Text, nullable=True)
    op.create_table(
        "identity_external_identities",
        sa.Column("issuer", sa.Text, primary_key=True),
        sa.Column("subject", sa.Text, primary_key=True),
        sa.Column(
            "account_id",
            sa.Text,
            sa.ForeignKey("identity_accounts.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("sealed_tokens", sa.Text),
        sa.Column("signed_in_at", sa.Text, nullable=False),
        sa.Column("checked_at", sa.Text, nullable=False),
        sa.Column("next_check_at", sa.Text, nullable=False),
        sa.Column("access_until", sa.Text, nullable=False),
    )
    op.create_index(
        "ix_identity_external_identities_next_check_at",
        "identity_external_identities",
        ["next_check_at"],
    )
    op.create_table(
        "identity_account_groups",
        sa.Column(
            "account_id",
            sa.Text,
            sa.ForeignKey("identity_accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("name", sa.Text, primary_key=True),
    )
    op.create_table(
        "identity_sign_in_attempts",
        sa.Column("binding_hash", sa.Text, primary_key=True),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("nonce", sa.Text, nullable=False),
        sa.Column("code_verifier", sa.Text, nullable=False),
        sa.Column("return_to", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index(
        "ix_identity_sign_in_attempts_created_at", "identity_sign_in_attempts", ["created_at"]
    )


def downgrade() -> None:
    op.drop_table("identity_sign_in_attempts")
    op.drop_table("identity_account_groups")
    op.drop_table("identity_external_identities")
    # Accounts of identity providers have no password: they cannot exist before this revision.
    # SQLite migrates with foreign keys off, so their sessions and tokens go first, explicitly.
    op.execute(
        "DELETE FROM identity_sessions WHERE account_id IN "
        "(SELECT id FROM identity_accounts WHERE password_hash IS NULL)"
    )
    op.execute(
        "DELETE FROM identity_api_tokens WHERE account_id IN "
        "(SELECT id FROM identity_accounts WHERE password_hash IS NULL)"
    )
    op.execute("DELETE FROM identity_accounts WHERE password_hash IS NULL")
    # SQLite would recreate identity_accounts to restore NOT NULL, and a downgrade run with
    # foreign keys on would cascade that into every session and token. The earlier code always
    # writes a hash, so on SQLite the column simply stays nullable.
    if op.get_bind().dialect.name != "sqlite":
        op.alter_column("identity_accounts", "password_hash", existing_type=sa.Text, nullable=False)
