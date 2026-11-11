"""#245: the local Embeddings and Reranker adapters, over stand-ins of fastembed's models.

The real models run in ``tests/bootstrap/test_local_models.py``; here only what the adapters
add: batching, token counts, errors and the bounded thread pool.
"""

import asyncio
import threading
import time
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest

from exactdocs.retrieval.adapters.driven.local_models import (
    LocalEmbedder,
    LocalEmbeddingModels,
    LocalReranker,
)
from exactdocs.retrieval.errors import (
    EmbeddingFailedError,
    ProviderUnsupportedError,
    RerankerError,
)
from exactdocs.retrieval.ports.driven import Embeddings


class FakeEmbedding:
    """Vectors of the text's length; records every call and how many ran at once."""

    def __init__(self, *, fail: bool = False, short: bool = False, pause: float = 0.0) -> None:
        self.fail, self.short, self.pause = fail, short, pause
        self.calls: list[tuple[str, list[str]]] = []
        self.running = self.most = 0
        self.lock = threading.Lock()

    def _enter(self) -> None:
        with self.lock:
            self.running += 1
            self.most = max(self.most, self.running)
        time.sleep(self.pause)
        with self.lock:
            self.running -= 1
        if self.fail:
            message = "onnxruntime: invalid input"
            raise RuntimeError(message)

    def passage_embed(self, texts: Iterable[str], **kwargs: object) -> Iterator[list[float]]:
        texts = list(texts)
        self.calls.append(("passage", texts))
        assert kwargs == {"batch_size": len(texts)}
        self._enter()
        kept = texts[:-1] if self.short else texts
        return iter([[float(len(t)), 1.0] for t in kept])

    def query_embed(self, query: str | Iterable[str], **kwargs: object) -> Iterator[list[float]]:
        assert isinstance(query, str)
        assert kwargs == {}
        self.calls.append(("query", [query]))
        self._enter()
        return iter([[float(len(query)), 0.0]])

    def token_count(self, texts: str | Iterable[str], **kwargs: object) -> int:
        del kwargs
        texts = [texts] if isinstance(texts, str) else list(texts)
        return sum(len(t.split()) + 2 for t in texts)


class BlockedEmbedding(FakeEmbedding):
    """Document batches wait for ``release``; queries answer at once."""

    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()
        self.batches_started = threading.Semaphore(0)

    def passage_embed(self, texts: Iterable[str], **kwargs: object) -> Iterator[list[float]]:
        self.batches_started.release()
        assert self.release.wait(10)
        return super().passage_embed(texts, **kwargs)


class FakeCrossEncoder:
    """Scores a document by the words it shares with the query."""

    def __init__(self, *, fail: bool = False, short: bool = False) -> None:
        self.fail, self.short = fail, short
        self.batch_sizes: list[object] = []

    def rerank(self, query: str, documents: Iterable[str], **kwargs: object) -> Iterator[float]:
        self.batch_sizes.append(kwargs.get("batch_size"))
        if self.fail:
            message = "onnxruntime: out of memory"
            raise RuntimeError(message)
        words = set(query.split())
        scores = [float(len(words & set(d.split()))) for d in documents]
        return iter(scores[:-1] if self.short else scores)


@pytest.fixture
def executor() -> Iterator[ThreadPoolExecutor]:
    with ThreadPoolExecutor(max_workers=2) as pool:
        yield pool


def _embeddings(
    model: FakeEmbedding, executor: ThreadPoolExecutor, batch_size: int = 2
) -> Embeddings:
    handle = LocalEmbedder(model=model, dimensions=2, executor=executor, query_executor=executor)
    return LocalEmbeddingModels().bind(
        handle, name="offline:BAAI/bge-small-en-v1.5", dimensions=None, batch_size=batch_size
    )


async def test_documents_are_embedded_in_batches_with_their_tokens_counted(
    executor: ThreadPoolExecutor,
) -> None:
    model = FakeEmbedding()
    embeddings = _embeddings(model, executor)

    embedded = await embeddings.embed_documents(["a b", "ccc", "dd d d"])

    assert embedded.vectors == ((3.0, 1.0), (3.0, 1.0), (6.0, 1.0))
    assert [texts for kind, texts in model.calls] == [["a b", "ccc"], ["dd d d"]]
    assert (embedded.input_tokens, embedded.requests) == (2 + 2 + 1 + 2 + 3 + 2, 2)
    assert await embeddings.dimensions() == 2


async def test_a_query_is_embedded_as_a_query(executor: ThreadPoolExecutor) -> None:
    model = FakeEmbedding()

    embedded = await _embeddings(model, executor).embed_query("retry failed calls")

    assert model.calls == [("query", ["retry failed calls"])]
    assert embedded.vectors == ((18.0, 0.0),)
    assert (embedded.input_tokens, embedded.requests) == (5, 1)


async def test_a_failing_model_is_an_embedding_error_that_retrying_will_not_fix(
    executor: ThreadPoolExecutor,
) -> None:
    embeddings = _embeddings(FakeEmbedding(fail=True), executor)

    with pytest.raises(EmbeddingFailedError) as raised:
        await embeddings.embed_documents(["a"])

    assert not raised.value.transient
    assert "RuntimeError" in str(raised.value)
    assert "invalid input" not in str(raised.value)  # the model's own text is not repeated


async def test_a_missing_vector_is_an_embedding_error(executor: ThreadPoolExecutor) -> None:
    with pytest.raises(EmbeddingFailedError, match="1 vectors for 2 texts"):
        await _embeddings(FakeEmbedding(short=True), executor).embed_documents(["a", "b"])


async def test_no_more_calls_run_at_once_than_the_pool_allows() -> None:
    model = FakeEmbedding(pause=0.05)
    with ThreadPoolExecutor(max_workers=1) as pool:
        embeddings = _embeddings(model, pool)
        await asyncio.gather(*(embeddings.embed_query(f"q{i}") for i in range(4)))

    assert model.most == 1


async def test_the_event_loop_keeps_running_while_a_model_works(
    executor: ThreadPoolExecutor,
) -> None:
    embeddings = _embeddings(FakeEmbedding(pause=0.2), executor)
    ticks = 0

    async def tick() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    ticker = asyncio.create_task(tick())
    await embeddings.embed_query("q")
    ticker.cancel()

    assert ticks >= 5


def test_other_configured_dimensions_than_the_model_makes_are_refused(
    executor: ThreadPoolExecutor,
) -> None:
    handle = LocalEmbedder(
        model=FakeEmbedding(), dimensions=384, executor=executor, query_executor=executor
    )

    with pytest.raises(ProviderUnsupportedError, match="384 dimensions, not 256"):
        LocalEmbeddingModels().bind(handle, name="offline:m", dimensions=256, batch_size=8)
    assert LocalEmbeddingModels().bind(handle, name="offline:m", dimensions=384, batch_size=8)


def test_only_a_local_model_can_be_bound() -> None:
    with pytest.raises(ProviderUnsupportedError, match="no local embedding model"):
        LocalEmbeddingModels().bind(object(), name="offline:m", dimensions=None, batch_size=8)


async def test_the_reranker_scores_each_document_in_small_batches(
    executor: ThreadPoolExecutor,
) -> None:
    model = FakeCrossEncoder()
    reranker = LocalReranker(model=model, executor=executor)

    scores = await reranker.rerank("retry failed calls", ["retry calls", "tokens", "failed"])

    assert scores == [2.0, 0.0, 1.0]
    assert model.batch_sizes == [8]
    assert await reranker.rerank("q", []) == []


@pytest.mark.parametrize(
    ("model", "message"),
    [
        (FakeCrossEncoder(fail=True), r"local model failed \(RuntimeError\)"),
        (FakeCrossEncoder(short=True), "gave 1 scores for 2 texts"),
    ],
)
async def test_a_failing_reranker_is_a_reranker_error(
    executor: ThreadPoolExecutor, model: FakeCrossEncoder, message: str
) -> None:
    with pytest.raises(RerankerError, match=message):
        await LocalReranker(model=model, executor=executor).rerank("q", ["a", "b"])


async def test_a_search_is_not_starved_while_document_batches_hold_their_pool() -> None:
    """Query embeddings and reranks run on their own pool, never behind an embedding job."""
    model = BlockedEmbedding()
    with (
        ThreadPoolExecutor(max_workers=1) as documents,
        ThreadPoolExecutor(max_workers=2) as queries,
    ):
        handle = LocalEmbedder(
            model=model, dimensions=2, executor=documents, query_executor=queries
        )
        embeddings = LocalEmbeddingModels().bind(
            handle, name="offline:m", dimensions=None, batch_size=1
        )
        ingestion = [
            asyncio.create_task(embeddings.embed_documents(["a b", "c"])) for _ in range(2)
        ]
        assert await asyncio.to_thread(model.batches_started.acquire, True, 5)

        query = await asyncio.wait_for(embeddings.embed_query("retry"), timeout=2)
        scores = await asyncio.wait_for(
            LocalReranker(model=FakeCrossEncoder(), executor=queries).rerank("a", ["a", "b"]),
            timeout=2,
        )

        assert query.vectors == ((5.0, 0.0),)
        assert scores == [1.0, 0.0]
        assert not any(task.done() for task in ingestion)  # the batches are still blocked
        model.release.set()
        done = await asyncio.gather(*ingestion)
    assert [d.requests for d in done] == [2, 2]


async def test_a_local_model_embeds_at_most_16_texts_per_call(
    executor: ThreadPoolExecutor,
) -> None:
    model = FakeEmbedding()

    embedded = await _embeddings(model, executor, batch_size=64).embed_documents(["t"] * 40)

    assert [len(texts) for _, texts in model.calls] == [16, 16, 8]
    assert embedded.requests == 3
