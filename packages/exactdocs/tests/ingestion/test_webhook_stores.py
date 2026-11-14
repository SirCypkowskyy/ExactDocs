"""Adapter contract: every ``WebhookSecrets`` and ``WebhookDeliveries`` behaves the same."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from databases import SQL_BACKENDS
from exactdocs.bootstrap.constants import CREDENTIALS_KEY_PURPOSE, WEBHOOK_SECRETS_PURPOSE
from exactdocs.bootstrap.database import migrate, open_database
from exactdocs.bootstrap.secret_box import FernetSecretBox
from exactdocs.bootstrap.settings import Settings
from exactdocs.ingestion.adapters.driven.memory import (
    InMemoryWebhookDeliveries,
    InMemoryWebhookSecrets,
)
from exactdocs.ingestion.adapters.driven.sqlite import (
    SqliteWebhookDeliveries,
    SqliteWebhookSecrets,
)
from exactdocs.ingestion.errors import WebhookSecretUnreadableError
from exactdocs.ingestion.models import Webhook, WebhookDelivery, WebhookProvider
from exactdocs.ingestion.ports import WebhookDeliveries, WebhookSecrets

T0 = datetime(2026, 11, 13, 9, 0, 0, 123456, tzinfo=UTC)
KEY = "k" * 40
SECRET = "s3cret-Webhook_value-0123456789abcdefghijk"


def box(purpose: bytes = WEBHOOK_SECRETS_PURPOSE) -> FernetSecretBox:
    return FernetSecretBox.from_secret(KEY, purpose=purpose)


@pytest.fixture(params=["memory", *SQL_BACKENDS])
async def stores(
    request: pytest.FixtureRequest,
) -> AsyncIterator[tuple[WebhookSecrets, WebhookDeliveries]]:
    if request.param == "memory":
        yield InMemoryWebhookSecrets(), InMemoryWebhookDeliveries()
        return
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    engine = open_database(Settings())
    await migrate(engine)
    yield SqliteWebhookSecrets(engine=engine, box=box()), SqliteWebhookDeliveries(engine=engine)
    await engine.dispose()


def delivery(
    delivery_id: str = "d-1", *, minutes: int = 0, library: str = "/a/b"
) -> WebhookDelivery:
    return WebhookDelivery(
        library=library,
        provider=WebhookProvider.GITHUB,
        delivery_id=delivery_id,
        received_at=T0 + timedelta(minutes=minutes),
    )


async def test_a_secret_round_trips_is_replaced_and_forgotten(
    stores: tuple[WebhookSecrets, WebhookDeliveries],
) -> None:
    secrets, _ = stores
    assert await secrets.get("/a/b") is None
    assert await secrets.created_at("/a/b") is None

    await secrets.save(Webhook(library="/a/b", secret=SECRET, created_at=T0))
    assert await secrets.get("/a/b") == Webhook(library="/a/b", secret=SECRET, created_at=T0)
    assert await secrets.created_at("/a/b") == T0
    assert await secrets.get("/c/d") is None

    later = T0 + timedelta(days=1)
    await secrets.save(Webhook(library="/a/b", secret="rotated", created_at=later))
    assert await secrets.get("/a/b") == Webhook(library="/a/b", secret="rotated", created_at=later)

    await secrets.delete("/a/b")
    await secrets.delete("/a/b")
    assert await secrets.get("/a/b") is None


async def test_the_secret_is_never_in_its_repr() -> None:
    assert SECRET not in repr(Webhook(library="/a/b", secret=SECRET, created_at=T0))


async def test_a_delivery_is_new_once(stores: tuple[WebhookSecrets, WebhookDeliveries]) -> None:
    _, deliveries = stores
    prune = T0 - timedelta(days=7)

    assert await deliveries.record(delivery(), prune_before=prune)
    assert not await deliveries.record(delivery(minutes=1), prune_before=prune)
    assert await deliveries.record(delivery("d-2"), prune_before=prune)
    assert await deliveries.record(delivery(library="/c/d"), prune_before=prune)
    gitlab = WebhookDelivery(
        library="/a/b", provider=WebhookProvider.GITLAB, delivery_id="d-1", received_at=T0
    )
    assert await deliveries.record(gitlab, prune_before=prune)

    await deliveries.forget(delivery())
    assert await deliveries.record(delivery(), prune_before=prune)  # the forge's retry

    await deliveries.delete_for("/a/b")
    assert await deliveries.record(delivery("d-2"), prune_before=prune)
    assert not await deliveries.record(delivery(library="/c/d"), prune_before=prune)


async def test_old_deliveries_are_pruned_when_one_is_recorded(
    stores: tuple[WebhookSecrets, WebhookDeliveries],
) -> None:
    _, deliveries = stores
    assert await deliveries.record(delivery("old"), prune_before=T0 - timedelta(days=7))
    assert await deliveries.record(delivery("recent", minutes=60), prune_before=T0)

    week_later = T0 + timedelta(days=7, minutes=30)
    assert await deliveries.record(
        delivery("new", minutes=60 * 24 * 7 + 30), prune_before=week_later - timedelta(days=7)
    )

    # "old" was pruned: the same ID is new again; "recent" is still remembered.
    assert await deliveries.record(delivery("old", minutes=60 * 24 * 8), prune_before=T0)
    assert not await deliveries.record(delivery("recent", minutes=60 * 24 * 8), prune_before=T0)


async def test_concurrent_records_of_one_delivery_have_one_winner(
    stores: tuple[WebhookSecrets, WebhookDeliveries],
) -> None:
    _, deliveries = stores
    prune = T0 - timedelta(days=7)

    won = await asyncio.gather(
        *(deliveries.record(delivery(), prune_before=prune) for _ in range(8))
    )

    assert sorted(won) == [False] * 7 + [True]


@pytest.mark.parametrize("backend", SQL_BACKENDS)
async def test_the_database_holds_no_plaintext_and_another_purpose_cannot_open_it(
    backend: str, request: pytest.FixtureRequest
) -> None:
    if backend == "postgres":
        request.getfixturevalue("on_postgres")
    engine = open_database(Settings())
    await migrate(engine)
    try:
        await SqliteWebhookSecrets(engine=engine, box=box()).save(
            Webhook(library="/a/b", secret=SECRET, created_at=T0)
        )
        async with engine.connect() as connection:
            stored = (
                await connection.execute(text("SELECT sealed FROM ingestion_webhooks"))
            ).scalar()
        assert stored is not None
        assert SECRET not in stored

        credentials_box = SqliteWebhookSecrets(engine=engine, box=box(CREDENTIALS_KEY_PURPOSE))
        with pytest.raises(WebhookSecretUnreadableError):
            await credentials_box.get("/a/b")
        assert await credentials_box.created_at("/a/b") == T0  # not opened
    finally:
        await engine.dispose()


def test_the_webhook_secrets_keep_their_own_purpose() -> None:
    # Changing it would make every stored webhook secret unreadable.
    assert WEBHOOK_SECRETS_PURPOSE == b"exactdocs webhook secrets v1"
    assert WEBHOOK_SECRETS_PURPOSE != CREDENTIALS_KEY_PURPOSE
