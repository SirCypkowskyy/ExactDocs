"""The revision that indexes a library's jobs by ID, up and down, on SQLite and PostgreSQL."""

import pytest
from alembic import command
from sqlalchemy import Connection, inspect

from databases import SQL_BACKENDS
from exactdocs.bootstrap.database import alembic_config, migrate, open_database
from exactdocs.bootstrap.settings import Settings

BEFORE, AFTER = "54e07d1ba829", "3d8919f935dd"


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


def _library_indexes(connection: Connection) -> dict[str, list[str | None]]:
    """Return the indexes of ``ingestion_jobs`` whose first column is ``library``.

    Args:
        connection: A connection to the database.

    Returns:
        Each index's name and columns.
    """
    return {
        index["name"]: index["column_names"]
        for index in inspect(connection).get_indexes("ingestion_jobs")
        if index["column_names"][:1] == ["library"]
        and index["name"] is not None
        and not index.get("unique")
    }


@pytest.mark.parametrize("backend", SQL_BACKENDS)
async def test_a_library_s_jobs_are_indexed_by_id_and_the_revision_goes_back(
    backend: str, request: pytest.FixtureRequest
) -> None:
    if backend == "postgres":
        request.getfixturevalue("on_postgres")
    engine = open_database(Settings())
    await migrate(engine)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(_alembic, "downgrade", AFTER)  # later revisions add more
            after = await connection.run_sync(_library_indexes)
            await connection.run_sync(_alembic, "downgrade", BEFORE)
            before = await connection.run_sync(_library_indexes)
            await connection.run_sync(_alembic, "upgrade", AFTER)
            again = await connection.run_sync(_library_indexes)
    finally:
        await engine.dispose()

    assert after == again == {"ingestion_jobs_library_id": ["library", "id"]}
    assert before == {"ingestion_jobs_library": ["library", "created_at"]}
