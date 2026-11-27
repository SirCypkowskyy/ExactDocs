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


@pytest.mark.parametrize("backend", SQL_BACKENDS)
async def test_access_events_get_a_rule_and_lose_rule_events_on_downgrade(
    backend: str, request: pytest.FixtureRequest
) -> None:
    if backend == "postgres":
        request.getfixturevalue("on_postgres")
    engine = open_database(Settings())
    try:
        await migrate(engine)
        async with engine.begin() as connection:
            columns = await connection.run_sync(
                lambda sync: {
                    c["name"] for c in inspect(sync).get_columns("identity_access_events")
                }
            )
            assert "rule" in columns
            await connection.execute(
                text(
                    "INSERT INTO identity_access_events (id, library, at, change, rule) VALUES"
                    " ('1', '', 't', 'rule_added', '{}'),"
                    " ('2', '/a/b', 't', 'library_deleted', NULL)"
                )
            )
            await connection.run_sync(_migrate, "downgrade", AFTER)
            ids = await connection.execute(text("SELECT id FROM identity_access_events"))
            assert ids.scalars().all() == ["2"]
    finally:
        await engine.dispose()
