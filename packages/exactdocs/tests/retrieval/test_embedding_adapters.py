"""RET-01: the adapters of the embedding jobs, without any provider.

pydantic-ai's ``TestEmbeddingModel`` stands in for a real model: CI never calls a provider.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest
from pydantic_ai import Embedder
from pydantic_ai.embeddings import TestEmbeddingModel
from pydantic_ai.exceptions import ModelHTTPError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from databases import SQL_BACKENDS
from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.retrieval.adapters.driven.ai_embeddings import PydanticAiEmbeddingModels
from exactdocs.retrieval.adapters.driven.genai_prices import GenaiPrices
from exactdocs.retrieval.adapters.driven.memory import InMemorySpendLedger
from exactdocs.retrieval.adapters.driven.sqlite import (
    SqliteChunkRepository,
    SqliteSpendLedger,
    ai_spend,
)
from exactdocs.retrieval.dtos import (
    ArticleChunksIn,
    ChunkIn,
    IndexManifestCommand,
)
from exactdocs.retrieval.errors import (
    EmbeddingFailedError,
    ProviderUnsupportedError,
)
from exactdocs.retrieval.models import (
    EmbeddingSource,
    SpendEntry,
    SpendKey,
    SpendWindow,
    embedding_spend,
)

T0 = datetime(2026, 11, 7, 23, 59, tzinfo=UTC)


def _model(model: TestEmbeddingModel, *, dimensions: int | None = None, batch: int = 2):
    return PydanticAiEmbeddingModels().bind(
        Embedder(model), name="corp:e5", dimensions=dimensions, batch_size=batch
    )


# ---------------------------------------------------------------- pydantic-ai's Embedder


async def test_texts_are_embedded_in_batches_with_the_usage_the_provider_returned() -> None:
    test = TestEmbeddingModel("e5", dimensions=3)
    model = _model(test, batch=2)

    embedded = await model.embed_documents(["a", "bb", "ccc", "dddd", "eeeee"])

    assert len(embedded.vectors) == 5
    assert all(len(v) == 3 for v in embedded.vectors)
    assert embedded.requests == 3
    assert embedded.input_tokens > 0
    assert model.name == "corp:e5"


async def test_without_configured_dimensions_the_model_is_asked_once() -> None:
    test = TestEmbeddingModel("e5", dimensions=7)
    model = _model(test)

    with patch.object(Embedder, "count_tokens", side_effect=AssertionError("no tokenizer")):
        assert await model.dimensions() == 7
        assert await model.dimensions() == 7
        await model.embed_documents(["text"])


async def test_configured_dimensions_are_sent_with_every_call() -> None:
    test = TestEmbeddingModel("e5", dimensions=7)
    model = _model(test, dimensions=4)

    embedded = await model.embed_documents(["text"])
    query = await model.embed_query("query")

    assert await model.dimensions() == 4
    assert test.last_settings is not None
    assert test.last_settings.get("dimensions") == 4
    assert len(embedded.vectors[0]) == len(query.vectors[0]) == 4


async def test_a_failed_call_names_the_model_and_status_never_the_message() -> None:
    model = _model(TestEmbeddingModel("e5"))
    error = ModelHTTPError(status_code=401, model_name="e5", body={"key": "sk-secret"})

    with (
        patch.object(TestEmbeddingModel, "embed", side_effect=error),
        pytest.raises(EmbeddingFailedError) as raised,
    ):
        await model.embed_documents(["text"])

    assert "corp:e5" in str(raised.value)
    assert "401" in str(raised.value)
    assert "sk-secret" not in str(raised.value)


@pytest.mark.parametrize(
    ("status", "transient"), [(429, True), (503, True), (408, True), (401, False), (404, False)]
)
async def test_a_failed_call_says_whether_asking_again_may_help(
    status: int, *, transient: bool
) -> None:
    model = _model(TestEmbeddingModel("e5"))
    error = ModelHTTPError(status_code=status, model_name="e5", body=None)

    with (
        patch.object(TestEmbeddingModel, "embed", side_effect=error),
        pytest.raises(EmbeddingFailedError) as raised,
    ):
        await model.embed_documents(["text"])

    assert raised.value.transient is transient


async def test_a_handle_that_is_no_embedder_is_refused() -> None:
    with pytest.raises(ProviderUnsupportedError):
        PydanticAiEmbeddingModels().bind(object(), name="corp:e5", dimensions=None, batch_size=2)


# ---------------------------------------------------------------- prices


def test_prices_come_from_the_bundled_price_list() -> None:
    prices = GenaiPrices()

    assert prices.input_usd_per_million("openai", "text-embedding-3-small") == pytest.approx(0.02)
    # A gateway serving one of OpenAI's models is priced as OpenAI prices it.
    gateway = prices.input_usd_per_million("openai-compatible", "text-embedding-3-small")
    assert gateway == pytest.approx(0.02)
    routed = prices.input_usd_per_million("openrouter", "openai/text-embedding-3-large")
    assert routed == pytest.approx(0.13)
    assert prices.input_usd_per_million("ollama", "nomic-embed-text") is None
    # A model the instance runs itself is never priced from another provider's list.
    assert prices.input_usd_per_million("ollama", "text-embedding-3-small") is None
    assert prices.input_usd_per_million("vllm", "text-embedding-3-small") is None
    assert prices.input_usd_per_million("local", "text-embedding-3-small") is None


# ---------------------------------------------------------------- the spend ledger


@pytest.fixture(params=SQL_BACKENDS)
async def container(request: pytest.FixtureRequest) -> AsyncIterator[Container]:
    """The app on each SQL database, with an embedding model configured.

    Yields:
        The running container.
    """
    if request.param == "postgres":
        request.getfixturevalue("on_postgres")
    ai = AiSettings.model_validate(
        {
            "providers": {
                "corp": {"kind": "openai-compatible", "base_url": "http://127.0.0.1:9/v1"}
            },
            "embedding": {"model": "corp:e5"},
        }
    )
    built = Container.build(Settings(ai=ai))
    async with built.running(jobs=False):
        yield built


@pytest.fixture
def engine(container: Container) -> AsyncEngine:
    return container.engine


async def test_the_sqlite_ledger_adds_usage_to_its_rows(engine: AsyncEngine) -> None:
    ledger = SqliteSpendLedger(engine=engine)
    memory = InMemorySpendLedger()
    first = embedding_spend(
        T0, library="/acme/x", input_tokens=100, requests=1, usd_per_million=0.02
    )
    second = embedding_spend(
        T0, library="/acme/x", input_tokens=50, requests=2, usd_per_million=None
    )

    for store in (ledger, memory):
        await store.add(first)
        await store.add(second)
        await store.add(())

    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                select(ai_spend).order_by(ai_spend.c.scope_kind, ai_spend.c.window_kind)
            )
        ).all()
    assert [
        (r.scope_kind, r.scope_id, r.window_kind, r.window_start, r.input_tokens, r.requests)
        for r in rows
    ] == [
        ("embedding", "", "day", "2026-11-07", 150, 3),
        ("embedding", "", "month", "2026-11-01", 150, 3),
        ("instance", "", "day", "2026-11-07", 150, 3),
        ("instance", "", "month", "2026-11-01", 150, 3),
        ("library", "/acme/x", "day", "2026-11-07", 150, 3),
        ("library", "/acme/x", "month", "2026-11-01", 150, 3),
    ]
    # The first call is priced (2 micro-USD), the second's two requests are not.
    assert {(r.usd_micros, r.unpriced) for r in rows} == {(2, 2)}
    assert {(row.usd_micros, row.unpriced) for row in memory.rows.values()} == {(2, 2)}
    assert {key.window for key in memory.rows} == {SpendWindow.DAY, SpendWindow.MONTH}


async def test_the_sql_ledger_reads_rows_and_counts_a_replayed_entry_once(
    engine: AsyncEngine,
) -> None:
    for ledger in (SqliteSpendLedger(engine=engine), InMemorySpendLedger()):
        day = SpendKey(
            scope_kind="user", scope_id="u1", window=SpendWindow.DAY, window_start=T0.date()
        )
        month = SpendKey(
            scope_kind="user",
            scope_id="u1",
            window=SpendWindow.MONTH,
            window_start=SpendWindow.MONTH.start(T0),
        )
        old = SpendKey(
            scope_kind="user", scope_id="u1", window=SpendWindow.DAY, window_start=date(2026, 10, 1)
        )
        response = [
            SpendEntry(
                scope_kind=k.scope_kind,
                scope_id=k.scope_id,
                window=k.window,
                window_start=k.window_start,
                input_tokens=7,
                output_tokens=3,
                requests=1,
                usd_micros=5,
                token="resp-1",
            )
            for k in (day, month)
        ]

        await ledger.add(response)
        await ledger.add(response)  # a replay: counted once
        await ledger.add([replace(response[0], token="resp-2")])
        await ledger.add([replace(response[0], window_start=old.window_start, token=None)])

        rows = await ledger.get(
            [
                day,
                month,
                old,
                SpendKey(
                    scope_kind="user", scope_id="u2", window=SpendWindow.DAY, window_start=T0.date()
                ),
            ]
        )
        assert {k: (r.tokens, r.requests, r.usd_micros) for k, r in rows.items()} == {
            day: (20, 2, 10),
            month: (10, 1, 5),
            old: (10, 1, 5),
        }, type(ledger)
        assert [(r.window, r.window_start) for r in await ledger.since(month.window_start)] == [
            (SpendWindow.DAY, day.window_start),
            (SpendWindow.MONTH, month.window_start),
        ], type(ledger)


async def test_the_sql_ledger_adds_up_across_concurrent_writers(engine: AsyncEngine) -> None:
    ledgers = [SqliteSpendLedger(engine=engine) for _ in range(4)]
    entries = embedding_spend(
        T0, library="/acme/x", input_tokens=1, requests=1, usd_per_million=1.0
    )

    await asyncio.gather(*(ledger.add(entries) for ledger in ledgers for _ in range(5)))

    rows = await ledgers[0].since(T0.date())
    assert {r.requests for r in rows if r.window is SpendWindow.DAY} == {20}


async def test_embedding_sources_are_read_on_every_sql_database(container: Container) -> None:
    await container.retrieval.index_manifest(
        IndexManifestCommand(
            manifest_id="m1",
            library="/acme/x",
            ref="v1",
            config_hash="cfg",
            articles=[
                ArticleChunksIn(
                    path=path,
                    blob_sha="b1",
                    chunks=[
                        ChunkIn(
                            heading_path=["Guide", "Retries"],
                            occurrence_index=0,
                            content="Use retry_policy.",
                            content_hash="h1",
                            anchor="retries",
                        )
                    ],
                )
                for path in ("docs/b.md", "docs/a.md")  # one blob at two paths
            ],
        )
    )

    found = await SqliteChunkRepository(engine=container.engine).embedding_sources(
        "m1", [("b1", "cfg", 0), ("zz", "cfg", 0)]
    )

    assert found == {
        ("b1", "cfg", 0): EmbeddingSource(
            article_path="docs/a.md", heading_path=("Guide", "Retries"), content="Use retry_policy."
        )
    }
