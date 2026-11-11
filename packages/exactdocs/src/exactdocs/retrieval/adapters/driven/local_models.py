"""Implements ``Embeddings`` and ``Reranker`` with models running in this process (#245).

The models are fastembed's ``TextEmbedding`` and ``TextCrossEncoder`` (the ``[local]`` extra), on
ONNX Runtime and the CPU. This module never imports fastembed: bootstrap's ``ModelFactory`` loads
the models from ``EXACTDOCS_MODELS_DIR`` and hands them over; here they are only called, through
the small structural types below. Every call runs on the factory's thread pool, which bounds how
many run at once, so the event loop never waits on a model. Nothing leaves the process.
"""

import asyncio
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import Executor
from dataclasses import dataclass, field
from functools import partial
from itertools import batched
from typing import Protocol

from exactdocs.retrieval.constants import (
    LOCAL_EMBEDDING_BATCH,
    LOCAL_MODEL_ERRORS,
    LOCAL_RERANK_BATCH,
    MAX_EMBEDDING_ERROR,
)
from exactdocs.retrieval.errors import (
    EmbeddingFailedError,
    ProviderUnsupportedError,
    RerankerError,
)
from exactdocs.retrieval.models import EmbeddedTexts
from exactdocs.retrieval.ports.driven import Embeddings


class TextEmbeddingModel(Protocol):
    """The part of fastembed's ``TextEmbedding`` that is called here."""

    def passage_embed(self, texts: Iterable[str], **kwargs: object) -> Iterable[Iterable[float]]:
        """Embed texts as documents.

        Args:
            texts: The texts.
            **kwargs: fastembed's options (``batch_size``).

        Returns:
            One vector (a NumPy array) per text.
        """
        ...

    def query_embed(
        self, query: str | Iterable[str], **kwargs: object
    ) -> Iterable[Iterable[float]]:
        """Embed a query, with the model's query prefix if it has one.

        Args:
            query: The query.
            **kwargs: fastembed's options.

        Returns:
            One vector per query.
        """
        ...

    def token_count(self, texts: str | Iterable[str], **kwargs: object) -> int:
        """Count the tokens of texts, as the model's tokenizer cuts them.

        Args:
            texts: The texts.
            **kwargs: fastembed's options.

        Returns:
            The tokens.
        """
        ...


class CrossEncoderModel(Protocol):
    """The part of fastembed's ``TextCrossEncoder`` that is called here."""

    def rerank(self, query: str, documents: Iterable[str], **kwargs: object) -> Iterable[float]:
        """Score each document against the query.

        Args:
            query: The query.
            documents: The documents.
            **kwargs: fastembed's options (``batch_size``).

        Returns:
            One score per document, in order.
        """
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class LocalEmbedder:
    """What ``ModelFactory.embedder`` builds for a ``local`` profile: a loaded model."""

    model: TextEmbeddingModel = field(repr=False)
    """The loaded model, shared by every caller in this process."""
    dimensions: int
    """How many numbers each of its vectors holds (fixed by the model)."""
    executor: Executor = field(repr=False)
    """Runs the document batches of the embedding jobs, one at a time."""
    query_executor: Executor = field(repr=False)
    """Runs query embeddings, apart from the batches, so a search never waits behind them."""
    errors: tuple[type[Exception], ...] = LOCAL_MODEL_ERRORS
    """What a failed call raises (ONNX Runtime's errors among them)."""


async def _run[T](executor: Executor, call: Callable[[], T]) -> T:
    """Run a blocking model call on the executor.

    Args:
        executor: The local models' thread pool.
        call: The call.

    Returns:
        What it returned.
    """
    return await asyncio.get_running_loop().run_in_executor(executor, call)


@dataclass(frozen=True, slots=True, kw_only=True)
class LocalEmbeddingModels:
    """Implements ``ports.driven.EmbeddingModels`` over a ``LocalEmbedder``."""

    def bind(
        self, handle: object, *, name: str, dimensions: int | None, batch_size: int
    ) -> Embeddings:
        """Wrap a loaded local model.

        Args:
            handle: What ``ModelFactory.embedder`` returned.
            name: ``<profile>:<model>``.
            dimensions: The configured dimensions, if any: a local model cannot shorten its
                vectors, so they must be the model's.
            batch_size: The most texts per call (at most ``LOCAL_EMBEDDING_BATCH``).

        Returns:
            The model.

        Raises:
            ProviderUnsupportedError: The handle is no local model, or other dimensions were
                configured than the model makes.
        """
        profile = name.partition(":")[0]
        if not isinstance(handle, LocalEmbedder):
            raise ProviderUnsupportedError(profile, "it built no local embedding model")
        if dimensions is not None and dimensions != handle.dimensions:
            reason = (
                f"the model makes vectors of {handle.dimensions} dimensions, not {dimensions}: "
                "unset EXACTDOCS_AI__EMBEDDING__DIMENSIONS"
            )
            raise ProviderUnsupportedError(profile, reason)
        return LocalEmbeddings(
            embedder=handle, name=name, batch_size=min(batch_size, LOCAL_EMBEDDING_BATCH)
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class LocalEmbeddings:
    """Implements ``ports.driven.Embeddings`` with a model in this process."""

    embedder: LocalEmbedder
    """The loaded model and its thread pool."""
    name: str
    """``<profile>:<model>``."""
    batch_size: int
    """The most texts per call."""

    async def dimensions(self) -> int:
        """Return the model's vector size (no call: the model fixes it).

        Returns:
            The size.
        """
        return self.embedder.dimensions

    async def embed_documents(self, texts: Sequence[str]) -> EmbeddedTexts:
        """Embed texts as documents, ``batch_size`` per call.

        Args:
            texts: The texts.

        Returns:
            One vector per text, and their tokens as the model's tokenizer counts them.
        """
        vectors: list[tuple[float, ...]] = []
        tokens = calls = 0
        for batch in batched(texts, self.batch_size, strict=False):
            embedded, counted = await self._call(
                partial(self._documents, list(batch)), self.embedder.executor
            )
            if len(embedded) != len(batch):
                reason = f"{len(embedded)} vectors for {len(batch)} texts"
                raise EmbeddingFailedError(self.name, reason)
            vectors.extend(embedded)
            tokens += counted
            calls += 1
        return EmbeddedTexts(vectors=tuple(vectors), input_tokens=tokens, requests=calls)

    async def embed_query(self, text: str) -> EmbeddedTexts:
        """Embed a query as a query (the model's query prefix, if it has one).

        Args:
            text: The query.

        Returns:
            Its vector and its tokens.
        """
        embedded, tokens = await self._call(
            partial(self._query, text), self.embedder.query_executor
        )
        return EmbeddedTexts(vectors=embedded, input_tokens=tokens, requests=1)

    def _documents(self, texts: list[str]) -> tuple[tuple[tuple[float, ...], ...], int]:
        """Embed documents (in the executor).

        Args:
            texts: One batch.

        Returns:
            The vectors and the tokens.
        """
        model = self.embedder.model
        vectors = tuple(
            tuple(float(x) for x in v) for v in model.passage_embed(texts, batch_size=len(texts))
        )
        return vectors, model.token_count(texts)

    def _query(self, text: str) -> tuple[tuple[tuple[float, ...], ...], int]:
        """Embed a query (in the executor).

        Args:
            text: The query.

        Returns:
            Its one vector and its tokens.
        """
        model = self.embedder.model
        vectors = tuple(tuple(float(x) for x in v) for v in model.query_embed(text))
        return vectors[:1], model.token_count(text)

    async def _call[T](self, call: Callable[[], T], executor: Executor) -> T:
        """Run a call on an executor, turning a failure into ``EmbeddingFailedError``.

        Args:
            call: The call.
            executor: The documents' pool or the queries'.

        Returns:
            Its result.

        Raises:
            EmbeddingFailedError: The model failed; not transient (it would fail again).
        """
        try:
            return await _run(executor, call)
        except self.embedder.errors as error:
            raise EmbeddingFailedError(
                self.name, type(error).__name__[:MAX_EMBEDDING_ERROR]
            ) from None


@dataclass(frozen=True, slots=True, kw_only=True)
class LocalReranker:
    """Implements ``ports.driven.Reranker`` with a cross-encoder in this process."""

    model: CrossEncoderModel = field(repr=False)
    """The loaded cross-encoder, shared by every caller in this process."""
    executor: Executor = field(repr=False)
    """Runs the calls on the query-time pool (never behind an embedding job's batches)."""
    errors: tuple[type[Exception], ...] = LOCAL_MODEL_ERRORS
    """What a failed call raises (ONNX Runtime's errors among them)."""

    async def rerank(self, query: str, documents: Sequence[str]) -> Sequence[float]:
        """Score each document against the query.

        Args:
            query: The query text.
            documents: The candidates' text.

        Returns:
            One score per document, in their order.

        Raises:
            RerankerError: The model failed or answered with the wrong number of scores.
        """
        if not documents:
            return []
        try:
            scores = await _run(self.executor, partial(self._scores, query, list(documents)))
        except self.errors as error:
            message = f"the local model failed ({type(error).__name__})"
            raise RerankerError(message) from None
        if len(scores) != len(documents):
            message = f"the local model gave {len(scores)} scores for {len(documents)} texts"
            raise RerankerError(message)
        return scores

    def _scores(self, query: str, documents: list[str]) -> list[float]:
        """Score (in the executor).

        Args:
            query: The query.
            documents: The documents.

        Returns:
            The scores.
        """
        return [
            float(s) for s in self.model.rerank(query, documents, batch_size=LOCAL_RERANK_BATCH)
        ]
