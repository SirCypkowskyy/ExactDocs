"""Implements ``ports.driven.Reranker`` over HTTP, in the two dialects rerank endpoints speak.

- **Cohere-compatible** (``POST <base_url>/rerank`` with ``model``, ``query`` and ``documents``,
  answering ``results`` of ``index`` and ``relevance_score``): Cohere (``.../v2``), Jina
  (``.../v1``), Voyage (``.../v1``, which answers ``data``), vLLM and LiteLLM (``/v1`` or
  ``/v2``), Azure AI Foundry's Cohere deployments. The base URL carries the version prefix.
- **TEI** (Hugging Face Text Embeddings Inference, ``POST <base_url>/rerank`` with ``query`` and
  ``texts``, answering a list of ``index`` and ``score``): the server serves one model.

Only the query and the candidates' text are sent, cut to ``MAX_RERANK_QUERY_CHARS`` and
``MAX_RERANK_DOCUMENT_CHARS``, in batches the endpoint accepts. Every failure, of the transport,
of the endpoint or of its answer, is a ``RerankerError`` that names no key, URL or text; the caller
keeps its own order then. The client is the profile's one ``httpx2`` client (bootstrap's
``ModelFactory``): its proxy, extra headers, host guard and overall timeout apply.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import httpx2

from exactdocs.retrieval.constants import (
    COHERE_RERANK_BATCH,
    MAX_RERANK_DOCUMENT_CHARS,
    MAX_RERANK_QUERY_CHARS,
    TEI_RERANK_BATCH,
)
from exactdocs.retrieval.errors import RerankerError


class RerankDialect(StrEnum):
    """Which request and answer shape the endpoint speaks."""

    COHERE = "cohere"
    """``documents`` in, ``results`` (or Voyage's ``data``) of ``relevance_score`` out."""
    TEI = "tei"
    """``texts`` in, a bare list of ``score`` out."""

    @property
    def batch(self) -> int:
        """The most documents one request may carry.

        Returns:
            ``COHERE_RERANK_BATCH`` or ``TEI_RERANK_BATCH``.
        """
        return COHERE_RERANK_BATCH if self is RerankDialect.COHERE else TEI_RERANK_BATCH


@dataclass(frozen=True, slots=True, kw_only=True)
class HttpReranker:
    """Implements ``ports.driven.Reranker`` with a profile's HTTP client."""

    client: httpx2.AsyncClient = field(repr=False)
    """The profile's client; it may reach the profile's endpoint only."""
    base_url: str
    """The endpoint, with its version prefix (``https://api.cohere.com/v2``); ``/rerank`` is
    added."""
    model: str
    """The rerank model (TEI ignores it: it serves one)."""
    key: str | None = field(default=None, repr=False)
    """Sent as ``Authorization: Bearer``; ``None`` for an endpoint without one."""
    dialect: RerankDialect = RerankDialect.COHERE
    """The request and answer shape."""

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        """Score each document against the query, in batches the endpoint accepts.

        Args:
            query: The query text.
            documents: The candidates' text.

        Returns:
            One score per document, in their order.
        """
        if not documents:
            return []
        texts = [d[:MAX_RERANK_DOCUMENT_CHARS] for d in documents]
        size = self.dialect.batch
        batches = [texts[i : i + size] for i in range(0, len(texts), size)]
        cut = query[:MAX_RERANK_QUERY_CHARS]
        try:
            # One failed batch cancels the others: the caller keeps its order anyway.
            async with asyncio.TaskGroup() as group:
                calls = [group.create_task(self._call(cut, batch)) for batch in batches]
        except* RerankerError as failed:
            raise failed.exceptions[0] from None
        return [score for call in calls for score in call.result()]

    async def _call(self, query: str, texts: list[str]) -> list[float]:
        """Make one rerank request.

        Args:
            query: The query text.
            texts: At most one batch of candidates.

        Returns:
            One score per text, in their order.

        Raises:
            RerankerError: The request failed, or its answer cannot be used.
        """
        if self.dialect is RerankDialect.TEI:
            body: dict[str, Any] = {"query": query, "texts": texts, "truncate": True}
        else:
            body = {"model": self.model, "query": query, "documents": texts}
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        try:
            response = await self.client.post(
                self.base_url.rstrip("/") + "/rerank", json=body, headers=headers
            )
        except (httpx2.HTTPError, RuntimeError) as error:
            # Its text may hold the URL: only the kind is told. RuntimeError: the profile's client
            # was closed under the call (the profile was edited or deleted meanwhile).
            raise RerankerError(type(error).__name__) from None
        if response.is_error:
            status = f"HTTP {response.status_code}"
            raise RerankerError(status)
        try:
            return _scores(response.json(), len(texts), self.dialect)
        except ValueError, KeyError, TypeError, IndexError:
            reason = "the answer is not a rerank result"
            raise RerankerError(reason) from None


def _scores(answer: object, count: int, dialect: RerankDialect) -> list[float]:
    """Read one score per candidate from an answer, whatever order it lists them in.

    Args:
        answer: The decoded JSON answer.
        count: How many candidates were sent.
        dialect: Its shape.

    Returns:
        The scores in the order the candidates were sent.

    Raises:
        TypeError: The answer holds no list of results.
        ValueError: A candidate has no score, or one has two.
    """
    if dialect is RerankDialect.TEI:
        items, key = answer, "score"
    elif isinstance(answer, dict):
        items, key = answer.get("results", answer.get("data")), "relevance_score"
    else:
        items, key = None, ""
    if not isinstance(items, list):
        reason = "no list of results"
        raise TypeError(reason)
    scores: dict[int, float] = {}
    for item in items:
        index, score = item["index"], item[key]
        # Strict: an index must be an integer, a score a number; JSON true is neither.
        if type(index) is not int or type(score) not in {int, float}:
            reason = "an index or a score is not a number"
            raise TypeError(reason)
        if not 0 <= index < count or index in scores:
            reason = "an index is out of range or repeated"
            raise ValueError(reason)
        scores[index] = float(score)
    if len(scores) != count:
        reason = "a candidate has no score"
        raise ValueError(reason)
    return [scores[i] for i in range(count)]
