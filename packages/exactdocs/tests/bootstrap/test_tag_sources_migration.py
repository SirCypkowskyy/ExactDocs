"""The revision that keeps imported tags by source, up and down, on SQLite and PostgreSQL."""

import pytest
from alembic import command
from sqlalchemy import Connection, inspect, text

from databases import SQL_BACKENDS
from exactdocs.bootstrap.database import alembic_config, migrate, open_database
from exactdocs.bootstrap.settings import Settings

BEFORE, AFTER = "97095cfef767", "e613cf99773e"
COLUMNS = {"front_matter_tags", "rule_tags"}


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


def _source_columns(connection: Connection) -> set[str]:
    """Return which of the source columns the entries table has.

    Args:
        connection: A connection to the database.

    Returns:
        The names among ``COLUMNS``.
    """
    names = {c["name"] for c in inspect(connection).get_columns("catalog_manifest_entries")}
    return names & COLUMNS


def _store_old_row(connection: Connection) -> None:
    """Store a library, a manifest and one entry as the revision before would.

    Args:
        connection: A connection to the database.
    """
    libraries = (
        "INSERT INTO catalog_libraries (id, title, description, source_url, host, settings)"
        " VALUES ('/acme/pay', 'Pay', '', 'https://x/acme/pay', 'github', '{}')"
    )
    manifests = (
        "INSERT INTO catalog_manifests (id, library_id, ref, kind, commit_sha, state, created_at)"
        " VALUES ('m1', '/acme/pay', 'main', 'branch', 'c', 'active', 't')"
    )
    contents = (
        "INSERT INTO catalog_article_contents (blob_sha, content_version, content)"
        " VALUES ('b', 1, 'x')"
    )
    entries = (
        "INSERT INTO catalog_manifest_entries"
        " (manifest_id, path, blob_sha, content_version, title, tags, front_matter, size)"
        """ VALUES ('m1', 'a.md', 'b', 1, 'A', '["api"]', '{}', 1)"""
    )
    for statement in (libraries, manifests, contents, entries):
        connection.execute(text(statement))


def _sources_of_old_row(connection: Connection) -> tuple[object, object]:
    """Return the source columns of the entry ``_store_old_row`` stored.

    Args:
        connection: A connection to the database.

    Returns:
        Its ``front_matter_tags`` and ``rule_tags``.
    """
    row = connection.execute(
        text("SELECT front_matter_tags, rule_tags FROM catalog_manifest_entries")
    ).one()
    return row.front_matter_tags, row.rule_tags


@pytest.mark.parametrize("backend", SQL_BACKENDS)
async def test_entries_gain_unrecorded_tag_sources_and_the_revision_goes_back(
    backend: str, request: pytest.FixtureRequest
) -> None:
    if backend == "postgres":
        request.getfixturevalue("on_postgres")
    engine = open_database(Settings())
    await migrate(engine)
    try:
        async with engine.begin() as connection:
            after = await connection.run_sync(_source_columns)
            await connection.run_sync(_alembic, "downgrade", BEFORE)
            before = await connection.run_sync(_source_columns)
            await connection.run_sync(_store_old_row)
            await connection.run_sync(_alembic, "upgrade", AFTER)
            again = await connection.run_sync(_source_columns)
            old_row = await connection.run_sync(_sources_of_old_row)
    finally:
        await engine.dispose()

    assert after == again == COLUMNS
    assert before == set()
    assert old_row == (None, None)  # not backfilled: read as origin "imported"
