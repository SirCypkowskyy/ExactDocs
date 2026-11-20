"""Legacy API tokens retain unrestricted user access after the scope migration."""

import pytest
from alembic import command
from sqlalchemy import Connection, inspect, text

from databases import SQL_BACKENDS
from exactdocs.bootstrap.database import alembic_config, migrate, open_database
from exactdocs.bootstrap.settings import Settings

BEFORE, AFTER = "3c5d9e1f7a42", "8e42a9c713f0"


def _migrate(connection: Connection, action: str, revision: str) -> None:
    config = alembic_config()
    config.attributes["connection"] = connection
    getattr(command, action)(config, revision)


@pytest.mark.parametrize("backend", SQL_BACKENDS)
async def test_legacy_tokens_keep_null_scope_and_survive_upgrade_and_downgrade(
    backend: str, request: pytest.FixtureRequest
) -> None:
    if backend == "postgres":
        request.getfixturevalue("on_postgres")
    engine = open_database(Settings())
    try:
        await migrate(engine)
        async with engine.begin() as connection:
            await connection.run_sync(_migrate, "downgrade", BEFORE)
            await connection.execute(
                text(
                    "INSERT INTO identity_accounts (id, username, password_hash, role, created_at)"
                    " VALUES ('ada', 'ada', 'hash', 'admin', 't')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO identity_api_tokens"
                    " (id, account_id, name, token_hash, prefix, created_at)"
                    " VALUES ('legacy', 'ada', 'old', 'hash', 'exd_old', 't')"
                )
            )
            await connection.run_sync(_migrate, "upgrade", AFTER)
            assert (
                await connection.execute(
                    text("SELECT library_ids FROM identity_api_tokens WHERE id = 'legacy'")
                )
            ).scalar_one() is None
            await connection.run_sync(_migrate, "downgrade", BEFORE)
            columns = await connection.run_sync(
                lambda sync: {
                    column["name"] for column in inspect(sync).get_columns("identity_api_tokens")
                }
            )
            assert "library_ids" not in columns
            assert (
                await connection.execute(text("SELECT id FROM identity_api_tokens"))
            ).scalar_one() == "legacy"
            await connection.run_sync(_migrate, "upgrade", AFTER)
            assert (
                await connection.execute(text("SELECT library_ids FROM identity_api_tokens"))
            ).scalar_one() is None
    finally:
        await engine.dispose()
