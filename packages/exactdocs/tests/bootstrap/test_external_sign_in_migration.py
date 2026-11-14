"""The external sign-in revision, up and down, on SQLite and PostgreSQL."""

import pytest
from alembic import command
from sqlalchemy import Connection, inspect, text

from databases import SQL_BACKENDS
from exactdocs.bootstrap.database import (
    _pragma,
    alembic_config,
    is_postgres,
    migrate,
    open_database,
)
from exactdocs.bootstrap.settings import Settings

BEFORE, AFTER = "bc0d89570be4", "b7e4c1a9d305"
TABLES = {"identity_external_identities", "identity_account_groups", "identity_sign_in_attempts"}


def _alembic(connection: Connection, action: str, revision: str) -> None:
    config = alembic_config()
    config.attributes["connection"] = connection
    getattr(command, action)(config, revision)


def _foreign_keys(connection: Connection, value: str) -> None:
    if connection.dialect.name == "sqlite":
        _pragma(connection, f"foreign_keys={value}")  # outside the transaction, as migrate does


def _state(connection: Connection) -> tuple[set[str], bool, list[str]]:
    inspector = inspect(connection)
    tables = set(inspector.get_table_names()) & TABLES
    nullable = next(
        c["nullable"]
        for c in inspector.get_columns("identity_accounts")
        if c["name"] == "password_hash"
    )
    accounts = connection.execute(text("SELECT username FROM identity_accounts ORDER BY 1"))
    return tables, nullable, [row.username for row in accounts]


def _store(connection: Connection, *, external: bool) -> None:
    people = [("ada", "$argon2id$x"), *([("alice", None)] if external else [])]
    for name, password_hash in people:
        connection.execute(
            text(
                "INSERT INTO identity_accounts (id, username, password_hash, role, created_at)"
                " VALUES (:id, :name, :hash, 'user', 't')"
            ),
            {"id": f"id-{name}", "name": name, "hash": password_hash},
        )
        connection.execute(
            text(
                "INSERT INTO identity_sessions (token_hash, account_id, created_at, last_used_at)"
                " VALUES (:token, :id, 't', 't')"
            ),
            {"token": f"s-{name}", "id": f"id-{name}"},
        )


def _sessions(connection: Connection) -> list[str]:
    rows = connection.execute(text("SELECT account_id FROM identity_sessions ORDER BY 1"))
    return [row.account_id for row in rows]


@pytest.mark.parametrize("backend", SQL_BACKENDS)
async def test_the_revision_goes_down_without_external_accounts_and_up_again(
    backend: str, request: pytest.FixtureRequest
) -> None:
    if backend == "postgres":
        request.getfixturevalue("on_postgres")
    engine = open_database(Settings())
    await migrate(engine)
    try:
        async with engine.connect() as connection:
            # SQLite migrates with foreign keys off (bootstrap.database.migrate does the same):
            # recreating identity_accounts must not cascade into its sessions.
            await connection.run_sync(_foreign_keys, "OFF")
            async with connection.begin():
                after = await connection.run_sync(_state)
                await connection.run_sync(_store, external=True)
                await connection.run_sync(_alembic, "downgrade", BEFORE)
                before = await connection.run_sync(_state)
                sessions_before = await connection.run_sync(_sessions)
                await connection.run_sync(_alembic, "upgrade", AFTER)
                again = await connection.run_sync(_state)
                sessions_again = await connection.run_sync(_sessions)
            await connection.run_sync(_foreign_keys, "ON")
        postgres = is_postgres(engine)
    finally:
        await engine.dispose()

    assert after == (TABLES, True, [])
    # The account without a password (and its session) cannot exist before the revision. On
    # SQLite the column stays nullable on the way down (no table rebuild: see the revision).
    assert before == (set(), backend == "sqlite", ["ada"])
    assert sessions_before == ["id-ada"]
    assert again == (TABLES, True, ["ada"])
    assert sessions_again == ["id-ada"]
    assert postgres is (backend == "postgres")
