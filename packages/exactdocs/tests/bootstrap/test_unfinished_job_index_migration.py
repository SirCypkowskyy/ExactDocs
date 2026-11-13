"""The revision that indexes a library's unfinished jobs, up and down, on SQLite and PostgreSQL."""

from typing import Any

import pytest
from alembic import command
from sqlalchemy import Connection, inspect

from databases import SQL_BACKENDS
from exactdocs.bootstrap.database import alembic_config, migrate, open_database
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.constants import UNFINISHED_JOBS_SQL

BEFORE, AFTER = "3d8919f935dd", "97095cfef767"
NAME = "ingestion_jobs_unfinished"


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


def _unfinished_index(connection: Connection) -> dict[str, Any] | None:
    """Return the columns and condition of the index of unfinished jobs, if it exists.

    Args:
        connection: A connection to the database.

    Returns:
        ``{"columns": ..., "where": ...}``, or ``None`` without the index.
    """
    for index in inspect(connection).get_indexes("ingestion_jobs"):
        if index["name"] == NAME:
            options = index.get("dialect_options", {})
            where = options.get("sqlite_where", options.get("postgresql_where"))
            return {
                "columns": index["column_names"],
                "where": str(where),
                "unique": index["unique"],
            }
    return None


@pytest.mark.parametrize("backend", SQL_BACKENDS)
async def test_a_library_s_unfinished_jobs_are_indexed_apart_and_the_revision_goes_back(
    backend: str, request: pytest.FixtureRequest
) -> None:
    if backend == "postgres":
        request.getfixturevalue("on_postgres")
    engine = open_database(Settings())
    await migrate(engine)
    try:
        async with engine.begin() as connection:
            after = await connection.run_sync(_unfinished_index)
            await connection.run_sync(_alembic, "downgrade", BEFORE)
            before = await connection.run_sync(_unfinished_index)
            await connection.run_sync(_alembic, "upgrade", AFTER)
            again = await connection.run_sync(_unfinished_index)
    finally:
        await engine.dispose()

    assert after == again
    assert after is not None
    assert after["columns"] == ["library", "id"]
    assert not after["unique"]
    if backend == "sqlite":
        # SQLite keeps the condition as written; the query must spell it the same, byte for byte.
        assert after["where"] == UNFINISHED_JOBS_SQL
    else:
        # PostgreSQL normalizes it (``state = ANY (ARRAY[...])``); it names the same states.
        assert "queued" in after["where"]
        assert "running" in after["where"]
    assert before is None
