"""The role rules migration (#577) marks the libraries that already have a credential private."""

import pytest
from alembic import command
from sqlalchemy import Connection, inspect, text

from databases import SQL_BACKENDS
from exactdocs.bootstrap.database import alembic_config, migrate, open_database
from exactdocs.bootstrap.settings import Settings

BEFORE, AFTER = "b5e8c2d4f7a1", "4a7c2e9b1d63"
TABLES = {"identity_role_rules", "identity_account_roles", "identity_private_libraries"}


def _migrate(connection: Connection, action: str, revision: str) -> None:
    config = alembic_config()
    config.attributes["connection"] = connection
    getattr(command, action)(config, revision)


def _tables(connection: Connection) -> set[str]:
    return set(inspect(connection).get_table_names())


@pytest.mark.parametrize("backend", SQL_BACKENDS)
async def test_libraries_with_a_credential_start_private(
    backend: str, request: pytest.FixtureRequest
) -> None:
    if backend == "postgres":
        request.getfixturevalue("on_postgres")
    engine = open_database(Settings())
    try:
        await migrate(engine)
        async with engine.begin() as connection:
            await connection.run_sync(_migrate, "downgrade", BEFORE)
            assert not TABLES & await connection.run_sync(_tables)
            await connection.execute(
                text(
                    "INSERT INTO ingestion_library_credentials (library, sealed)"
                    " VALUES ('/acme/secret', 'sealed')"
                )
            )
            await connection.run_sync(_migrate, "upgrade", AFTER)
            assert await connection.run_sync(_tables) >= TABLES
            private = await connection.execute(
                text("SELECT library FROM identity_private_libraries")
            )
            assert private.scalars().all() == ["/acme/secret"]
    finally:
        await engine.dispose()
