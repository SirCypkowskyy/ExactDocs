"""The revision that links each manifest to the version it follows, up and down, on SQLite and
PostgreSQL (#201)."""

import pytest
from alembic import command
from sqlalchemy import Connection, inspect, text

from databases import SQL_BACKENDS
from exactdocs.bootstrap.database import alembic_config, migrate, open_database
from exactdocs.bootstrap.settings import Settings

BEFORE, AFTER = "f91e59c59169", "4ffb525052ed"
# (manifest ID, ref, kind, the version its renames come from: none without renames)
MANIFESTS = [
    ("m-tag", "v1.4.0", "tag", "v1.3.0"),
    ("m-plain", "v1.3.0", "tag", None),
    ("m-branch", "main", "branch", "main"),
]


def _alembic(connection: Connection, action: str, revision: str) -> None:
    """Run an Alembic command on the connection.

    Args:
        connection: A connection to the database.
        action: ``"upgrade"`` or ``"downgrade"``.
        revision: The revision to go to.
    """
    config = alembic_config()
    config.attributes["connection"] = connection
    getattr(command, action)(config, revision)


def _seed(connection: Connection) -> None:
    """Store a library with a tag that has renames, one without and a branch, as before.

    Args:
        connection: A connection to the database, at ``BEFORE``.
    """
    connection.execute(
        text(
            "INSERT INTO catalog_libraries (id, title, description, source_url, host, settings) "
            "VALUES ('/acme/payments', 'Payments', '', 'https://github.com/acme/payments', "
            "'github', '{}')"
        )
    )
    for manifest_id, ref, kind, from_ref in MANIFESTS:
        connection.execute(
            text(
                "INSERT INTO catalog_manifests "
                "(id, library_id, ref, kind, commit_sha, state, created_at) "
                "VALUES (:id, '/acme/payments', :ref, :kind, :sha, 'active', '2026-11-13')"
            ),
            {"id": manifest_id, "ref": ref, "kind": kind, "sha": "a" * 40},
        )
        if from_ref is not None:
            for old, new in (("a.md", "b.md"), ("c.md", "d.md")):
                connection.execute(
                    text(
                        "INSERT INTO catalog_manifest_renames "
                        "(manifest_id, old_path, from_ref, new_path, similarity) "
                        "VALUES (:id, :old, :from_ref, :new, 80)"
                    ),
                    {"id": manifest_id, "old": old, "from_ref": from_ref, "new": new},
                )


def _links(connection: Connection) -> dict[str, str | None]:
    """Return each manifest's ``renamed_from``.

    Args:
        connection: A connection to the database, at ``AFTER``.

    Returns:
        The link of each manifest, by ID.
    """
    rows = connection.execute(text("SELECT id, renamed_from FROM catalog_manifests"))
    return {row.id: row.renamed_from for row in rows}


def _columns(connection: Connection) -> set[str]:
    """Return the columns of the manifests table.

    Args:
        connection: A connection to the database.

    Returns:
        The column names.
    """
    return {column["name"] for column in inspect(connection).get_columns("catalog_manifests")}


def _renames(connection: Connection) -> list[tuple[str, str, str]]:
    """Return every rename row.

    Args:
        connection: A connection to the database.

    Returns:
        ``(manifest ID, old path, from_ref)``, sorted.
    """
    rows = connection.execute(
        text("SELECT manifest_id, old_path, from_ref FROM catalog_manifest_renames")
    )
    return sorted((row.manifest_id, row.old_path, row.from_ref) for row in rows)


@pytest.mark.parametrize("backend", SQL_BACKENDS)
async def test_manifests_stored_before_get_the_link_their_renames_give_and_the_revision_goes_back(
    backend: str, request: pytest.FixtureRequest
) -> None:
    if backend == "postgres":
        request.getfixturevalue("on_postgres")
    engine = open_database(Settings())
    await migrate(engine)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(_alembic, "downgrade", BEFORE)
            await connection.run_sync(_seed)
            renames = await connection.run_sync(_renames)
            await connection.run_sync(_alembic, "upgrade", AFTER)
            links = await connection.run_sync(_links)
            await connection.run_sync(_alembic, "downgrade", BEFORE)
            columns = await connection.run_sync(_columns)
            kept = await connection.run_sync(_renames)
            await connection.run_sync(_alembic, "upgrade", AFTER)
            again = await connection.run_sync(_links)
    finally:
        await engine.dispose()

    assert links == {"m-tag": "v1.3.0", "m-plain": None, "m-branch": "main"}
    assert "renamed_from" not in columns
    assert len(renames) == 4
    assert kept == renames  # going back drops the link only, never a rename
    assert again == links
