"""Each manifest names the version its rename map was detected against (#201).

A path is followed from one version to another along these links, hop by hop. Until now only a
rename row held the link, so a version where nothing moved broke the chain. Manifests stored
before keep the link their renames give; one without renames has none until it is re-imported.

Revision ID: 4ffb525052ed
Revises: f91e59c59169
"""

import sqlalchemy as sa
from alembic import op

revision = "4ffb525052ed"
down_revision = "f91e59c59169"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("catalog_manifests", sa.Column("renamed_from", sa.Text))
    # Every rename of a manifest names the same version: the one its map was detected against.
    op.execute(
        "UPDATE catalog_manifests SET renamed_from = ("
        "SELECT min(r.from_ref) FROM catalog_manifest_renames r"
        " WHERE r.manifest_id = catalog_manifests.id)"
    )


def downgrade() -> None:
    op.drop_column("catalog_manifests", "renamed_from")
