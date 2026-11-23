"""Adapter contract: every ``PreferencesRepository`` behaves the same, whatever stores the data."""

import json
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from databases import SQL_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import Settings
from exactdocs.identity.adapters.driven.memory import InMemoryPreferencesRepository
from exactdocs.identity.adapters.driven.sqlite import (
    SqliteAccountRepository,
    SqlitePreferencesRepository,
)
from exactdocs.identity.models import (
    Account,
    AccountId,
    Contrast,
    Font,
    Language,
    Motion,
    Preferences,
    Role,
    TextSpacing,
    Theme,
    Username,
)
from exactdocs.identity.ports import PreferencesRepository

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
ADA = AccountId("id-ada")
BOB = AccountId("id-bob")
CHOSEN = Preferences(
    theme=Theme.DARK,
    contrast=Contrast.MORE,
    text_scale=125,
    text_spacing=TextSpacing.WIDE,
    motion=Motion.REDUCED,
    font=Font.HYPERLEGIBLE,
    underline_links=True,
    large_targets=True,
    language=Language.PL,
    library_logos=False,
)


@asynccontextmanager
async def database_with_two_accounts(
    backend: str, request: pytest.FixtureRequest
) -> AsyncGenerator[Container]:
    """Run a container on ``backend`` whose database holds the accounts Ada and Bob."""
    if backend == "postgres":
        request.getfixturevalue("on_postgres")
    container = Container.build(Settings())
    async with container.running(jobs=False):
        accounts = SqliteAccountRepository(engine=container.engine)
        for account_id, name in [(ADA, "ada"), (BOB, "bob")]:
            await accounts.add(
                Account(
                    id=account_id,
                    username=Username(name),
                    password_hash="$argon2id$x",
                    role=Role.USER,
                    created_at=NOW,
                )
            )
        yield container


@pytest.fixture(params=["memory", *SQL_BACKENDS])
async def repository(request: pytest.FixtureRequest) -> AsyncIterator[PreferencesRepository]:
    if request.param == "memory":
        yield InMemoryPreferencesRepository()
        return
    async with database_with_two_accounts(request.param, request) as container:
        yield SqlitePreferencesRepository(engine=container.engine)


@pytest.fixture(params=SQL_BACKENDS)
async def database(request: pytest.FixtureRequest) -> AsyncIterator[Container]:
    """Only a database keeps rows written by an older or newer release."""
    async with database_with_two_accounts(request.param, request) as container:
        yield container


async def test_an_account_that_never_saved_has_none(repository: PreferencesRepository) -> None:
    assert await repository.get(ADA) is None


async def test_saved_preferences_come_back_and_a_save_replaces_them(
    repository: PreferencesRepository,
) -> None:
    await repository.put(ADA, CHOSEN)
    assert await repository.get(ADA) == CHOSEN

    await repository.put(ADA, Preferences())
    assert await repository.get(ADA) == Preferences()


async def test_each_account_has_its_own(repository: PreferencesRepository) -> None:
    await repository.put(ADA, CHOSEN)

    assert await repository.get(BOB) is None
    await repository.put(BOB, Preferences(font=Font.SYSTEM))
    assert await repository.get(ADA) == CHOSEN
    assert await repository.get(BOB) == Preferences(font=Font.SYSTEM)


async def test_every_language_is_kept(repository: PreferencesRepository) -> None:
    for language in Language:
        await repository.put(ADA, Preferences(language=language))
        assert await repository.get(ADA) == Preferences(language=language)


@pytest.mark.parametrize(
    ("stored", "read"),
    [
        (
            {"theme": "dark", "text_scale": 95, "font": "comic-sans", "underline_links": "yes"},
            Preferences(theme=Theme.DARK),
        ),
        # A row from before the language preference, or one naming a language no longer offered.
        ({"theme": "light"}, Preferences(theme=Theme.LIGHT)),
        ({"language": "de", "contrast": "more"}, Preferences(contrast=Contrast.MORE)),
        ({"language": 7}, Preferences()),
        ({"language": "en"}, Preferences(language=Language.EN)),
        # A row from before library logos could be hidden shows them; only `false` hides them.
        ({"library_logos": "no", "large_targets": 1}, Preferences()),
        ({"library_logos": None}, Preferences()),
        ({"library_logos": False}, Preferences(library_logos=False)),
        (["not", "an", "object"], Preferences()),
    ],
)
async def test_a_setting_a_row_lacks_or_no_longer_offered_reads_as_its_default(
    database: Container, stored: object, read: Preferences
) -> None:
    async with database.engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO identity_preferences (account_id, preferences) VALUES (:id, :prefs)"),
            {"id": ADA, "prefs": json.dumps(stored)},
        )

    assert await SqlitePreferencesRepository(engine=database.engine).get(ADA) == read
