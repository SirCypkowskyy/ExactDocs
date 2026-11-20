"""Thinking levels of the llm and judge roles (#421).

``retrieval_library_settings`` gets a library's own level for each role (``llm_thinking``,
``judge_thinking``: a ``ThinkingLevel`` value, NULL for the instance's).
``retrieval_role_settings`` holds the instance roles' levels set over the REST API, one row per
role; a level set in the environment or the configuration file wins over it.

Revision ID: 5b7d2e8f4c61
Revises: 8e42a9c713f0
"""

import sqlalchemy as sa
from alembic import op

revision = "5b7d2e8f4c61"
down_revision = "8e42a9c713f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("retrieval_library_settings", sa.Column("llm_thinking", sa.Text))
    op.add_column("retrieval_library_settings", sa.Column("judge_thinking", sa.Text))
    op.create_table(
        "retrieval_role_settings",
        sa.Column("role", sa.Text, primary_key=True),
        sa.Column("thinking", sa.Text),
    )


def downgrade() -> None:
    op.drop_table("retrieval_role_settings")
    with op.batch_alter_table("retrieval_library_settings") as batch:
        batch.drop_column("judge_thinking")
        batch.drop_column("llm_thinking")
