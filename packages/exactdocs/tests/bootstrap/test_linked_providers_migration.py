"""The linked providers revision (#506), up and down, on SQLite and PostgreSQL."""

import pytest
from alembic import command
from sqlalchemy import Connection, inspect, text
from sqlalchemy.exc import IntegrityError

from databases import SQL_BACKENDS
from exactdocs.bootstrap.database import _pragma, alembic_config, migrate, open_database
from exactdocs.bootstrap.settings import Settings

BEFORE, AFTER = "6a1e4c9b2d75", "6f1d3b8a2c47"
IDENTITY = (
    "INSERT INTO identity_external_identities (issuer, subject, account_id, provider,"
    " signed_in_at, checked_at, next_check_at, access_until{linked_column})"
    " VALUES (:issuer, :subject, :account, :provider, 't', 't', 't', 't'{linked_value})"
)


def _alembic(connection: Connection, action: str, revision: str) -> None:
    config = alembic_config()
    config.attributes["connection"] = connection
    getattr(command, action)(config, revision)


def _foreign_keys(connection: Connection, value: str) -> None:
    if connection.dialect.name == "sqlite":
        _pragma(connection, f"foreign_keys={value}")  # outside the transaction, as migrate does


def _columns(connection: Connection) -> tuple[set[str], set[str]]:
    inspector = inspect(connection)
    identities = {c["name"] for c in inspector.get_columns("identity_external_identities")}
    attempts = {c["name"] for c in inspector.get_columns("identity_sign_in_attempts")}
    return identities & {"linked_at"}, attempts & {"link_session_hash"}


def _account(connection: Connection, name: str) -> None:
    connection.execute(
        text(
            "INSERT INTO identity_accounts (id, username, password_hash, role, created_at)"
            " VALUES (:id, :name, NULL, 'user', 't')"
        ),
        {"id": f"id-{name}", "name": name},
    )


def _identity(
    connection: Connection, subject: str, account: str, provider: str, *, linked: bool | None
) -> None:
    """Insert an identity; ``linked`` None: before the revision (no ``linked_at`` column)."""
    statement = IDENTITY.format(
        linked_column="" if linked is None else ", linked_at",
        linked_value="" if linked is None else ", :linked_at",
    )
    connection.execute(
        text(statement),
        {
            "issuer": f"https://{provider}.example.com",
            "subject": subject,
            "account": f"id-{account}",
            "provider": provider,
            "linked_at": "t" if linked else None,
        },
    )


def _refused(
    connection: Connection, subject: str, account: str, provider: str, *, linked: bool | None
) -> bool:
    """Whether inserting the identity is refused by a constraint (nothing is kept then)."""
    savepoint = connection.begin_nested()
    try:
        _identity(connection, subject, account, provider, linked=linked)
    except IntegrityError:
        savepoint.rollback()
        return True
    savepoint.commit()
    return False


def _subjects(connection: Connection) -> list[str]:
    rows = connection.execute(text("SELECT subject FROM identity_external_identities ORDER BY 1"))
    return [row.subject for row in rows]


def _attempts(connection: Connection) -> list[str]:
    rows = connection.execute(text("SELECT binding_hash FROM identity_sign_in_attempts"))
    return [row.binding_hash for row in rows]


def _attempt(connection: Connection, binding: str, session: str | None) -> None:
    connection.execute(
        text(
            "INSERT INTO identity_sign_in_attempts (binding_hash, provider, state, nonce,"
            " code_verifier, return_to, created_at, link_session_hash)"
            " VALUES (:binding, 'corp', 's', 'n', 'v', '/', 't', :session)"
        ),
        {"binding": binding, "session": session},
    )


def _scenario(connection: Connection) -> dict[str, object]:
    seen: dict[str, object] = {"after": _columns(connection)}
    _account(connection, "alice")
    _account(connection, "bob")
    _identity(connection, "a-1", "alice", "corp", linked=False)  # alice's origin
    _identity(connection, "a-2", "alice", "google", linked=True)
    seen["second_origin"] = _refused(connection, "a-3", "alice", "discord", linked=False)
    seen["second_google"] = _refused(connection, "a-4", "alice", "google", linked=True)
    seen["linked_discord"] = not _refused(connection, "a-5", "alice", "discord", linked=True)
    _attempt(connection, "sign-in", None)
    _attempt(connection, "link", "session-hash")

    _alembic(connection, "downgrade", BEFORE)
    seen["before"] = _columns(connection)
    seen["before_subjects"] = _subjects(connection)  # the linked identities went
    seen["before_attempts"] = _attempts(connection)
    seen["one_per_account"] = _refused(connection, "b-1", "alice", "other", linked=None)
    _identity(connection, "b-2", "bob", "corp", linked=None)

    _alembic(connection, "upgrade", AFTER)
    seen["again"] = _columns(connection)
    seen["again_subjects"] = _subjects(connection)
    seen["origin_kept"] = _refused(connection, "b-3", "bob", "other", linked=False)
    seen["link_again"] = not _refused(connection, "b-4", "bob", "other", linked=True)
    return seen


@pytest.mark.parametrize("backend", SQL_BACKENDS)
async def test_the_revision_goes_down_without_linked_identities_and_up_again(
    backend: str, request: pytest.FixtureRequest
) -> None:
    if backend == "postgres":
        request.getfixturevalue("on_postgres")
    engine = open_database(Settings())
    await migrate(engine)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_foreign_keys, "OFF")
            async with connection.begin():
                seen = await connection.run_sync(_scenario)
            await connection.run_sync(_foreign_keys, "ON")
    finally:
        await engine.dispose()

    assert seen == {
        "after": ({"linked_at"}, {"link_session_hash"}),
        "second_origin": True,  # one origin per account
        "second_google": True,  # one identity per (account, provider)
        "linked_discord": True,
        "before": (set(), set()),
        "before_subjects": ["a-1"],
        "before_attempts": ["sign-in"],
        "one_per_account": True,  # the unique account_id is back
        "again": ({"linked_at"}, {"link_session_hash"}),
        "again_subjects": ["a-1", "b-2"],
        "origin_kept": True,
        "link_again": True,
    }
