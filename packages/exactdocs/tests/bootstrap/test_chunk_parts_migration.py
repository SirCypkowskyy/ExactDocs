"""The revision that gives stored chunks their part index, up and down, on SQLite and PostgreSQL."""

import pytest
from alembic import command
from sqlalchemy import Connection, inspect, text

from databases import SQL_BACKENDS
from exactdocs.bootstrap.database import alembic_config, migrate, open_database
from exactdocs.bootstrap.settings import Settings

BEFORE, AFTER = "97095cfef767", "f91e59c59169"


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


def _columns(connection: Connection) -> set[str]:
    """Return the column names of ``retrieval_chunks``.

    Args:
        connection: A connection to the database.

    Returns:
        The names.
    """
    return {c["name"] for c in inspect(connection).get_columns("retrieval_chunks")}


def _store_a_chunk(connection: Connection) -> None:
    """Store one chunk the way a chunk set was stored before parts existed.

    Args:
        connection: A connection to the database.
    """
    connection.execute(
        text(
            "INSERT INTO retrieval_chunk_sets (blob_sha, config_hash, digest) "
            "VALUES ('b', 'c', 'd')"
        )
    )
    connection.execute(
        text(
            "INSERT INTO retrieval_chunks (blob_sha, config_hash, position, heading_path, "
            "occurrence_index, content, content_hash, anchor, code_languages) "
            "VALUES ('b', 'c', 0, '[\"A\"]', 0, 'text', 'h', 'a', '[]')"
        )
    )


@pytest.mark.parametrize("backend", SQL_BACKENDS)
async def test_stored_chunks_get_part_0_and_the_revision_goes_back(
    backend: str, request: pytest.FixtureRequest
) -> None:
    if backend == "postgres":
        request.getfixturevalue("on_postgres")
    engine = open_database(Settings())
    await migrate(engine)
    try:
        async with engine.begin() as connection:
            after = await connection.run_sync(_columns)
            await connection.run_sync(_alembic, "downgrade", BEFORE)
            before = await connection.run_sync(_columns)
            await connection.run_sync(_store_a_chunk)
            await connection.run_sync(_alembic, "upgrade", AFTER)
            again = await connection.run_sync(_columns)
            parts = (await connection.execute(text("SELECT part FROM retrieval_chunks"))).all()
    finally:
        await engine.dispose()

    assert "part" in after
    assert "part" not in before
    assert after == again
    assert [tuple(row) for row in parts] == [(0,)]  # a chunk stored before is a whole section
