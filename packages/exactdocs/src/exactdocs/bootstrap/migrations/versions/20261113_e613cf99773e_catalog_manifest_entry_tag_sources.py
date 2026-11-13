"""Manifest entries keep their imported tags by source: front matter and path rules (#215).

Both columns are NULL in the rows stored before: which imported tag came from where was not
recorded, and is not backfilled. The front matter could be parsed again here, but a tag both the
front matter and a path rule give would then pass as front matter only, and the rules a version
was tagged with may since have changed. An API reader sees such tags as `imported`; the next
import or tag-rule change of the version records their sources.

Revision ID: e613cf99773e
Revises: 4ffb525052ed
"""

import sqlalchemy as sa
from alembic import op

revision = "e613cf99773e"
down_revision = "4ffb525052ed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # JSON lists of normalized tags; NULL in rows stored before (not backfilled, see above).
    op.add_column("catalog_manifest_entries", sa.Column("front_matter_tags", sa.Text))
    op.add_column("catalog_manifest_entries", sa.Column("rule_tags", sa.Text))


def downgrade() -> None:
    with op.batch_alter_table("catalog_manifest_entries") as batch:
        batch.drop_column("rule_tags")
        batch.drop_column("front_matter_tags")
