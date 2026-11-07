"""The pydantic-ai side of ``ai_embeddings``: loaded only once an embedding model is called.

Tokens come from the ``usage`` each call returns; ``Embedder.count_tokens`` is never called (for
OpenAI models it would load tiktoken, which downloads its encoding files on first use).
"""

from collections.abc import Awaitable, Sequence
from dataclasses import dataclass, field
from itertools import batched

import httpx2
from azure.core.exceptions import AzureError
from google.genai.errors import APIError as GoogleAPIError
from openai import APIConnectionError, APITimeoutError, OpenAIError
from pydantic_ai import Embedder
from pydantic_ai.embeddings import EmbeddingResult, EmbeddingSettings
from pydantic_ai.exceptions import AgentRunError, ModelAPIError, ModelHTTPError, UserError

from exactdocs.retrieval.constants import (
    DIMENSIONS_PROBE,
    MAX_EMBEDDING_ERROR,
    SERVER_ERROR,
    TRANSIENT_STATUSES,
)
from exactdocs.retrieval.errors import EmbeddingFailedError, ProviderUnsupportedError
from exactdocs.retrieval.models import EmbeddedTexts


def _call_errors() -> tuple[type[Exception], ...]:
    """Name what a failed embedding call raises.

    Returns:
        The transport's, the SDKs' and pydantic-ai's errors, and the value errors of an answer
        that cannot be read.
    """
    return (
        httpx2.HTTPError,
        OpenAIError,
        GoogleAPIError,
        AzureError,
        AgentRunError,
        UserError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
    )


def _transient(error: Exception) -> bool:
    """Say whether asking again later may succeed: a timeout, a lost connection, a 429 or a 5xx.

    Args:
        error: What the call raised.

    Returns:
        True for those; False for an answer that will not change (401, 404, a bad request).
    """
    if isinstance(error, ModelHTTPError):
        return error.status_code in TRANSIENT_STATUSES or error.status_code >= SERVER_ERROR
    return isinstance(
        error, (ModelAPIError, httpx2.TransportError, APIConnectionError, APITimeoutError)
    )


def wrap(
    handle: object, *, name: str, dimensions: int | None, batch_size: int
) -> PydanticAiEmbeddings:
    """Narrow the factory's handle to an ``Embedder`` and wrap it.

    Args:
        handle: What ``ModelFactory.embedder`` returned.
        name: ``<profile>:<model>``.
        dimensions: The configured dimensions, if any.
        batch_size: The most texts per call.

    Returns:
        The model.

    Raises:
        ProviderUnsupportedError: The handle is not an ``Embedder``.
    """
    if not isinstance(handle, Embedder):
        raise ProviderUnsupportedError(name.partition(":")[0], "it built no embedding model")
    return PydanticAiEmbeddings(
        embedder=handle, name=name, configured=dimensions, batch_size=batch_size
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class PydanticAiEmbeddings:
    """Implements ``ports.driven.Embeddings`` over a pydantic-ai ``Embedder``."""

    embedder: Embedder
    """The embedder the factory built (explicit endpoint and key)."""
    name: str
    """``<profile>:<model>``."""
    configured: int | None
    """The configured dimensions, sent as ``EmbeddingSettings(dimensions=...)``."""
    batch_size: int
    """The most texts per call."""
    _probed: list[int] = field(default_factory=list, init=False, repr=False)
    """The dimensions the model answered, once asked."""

    def _settings(self) -> EmbeddingSettings | None:
        """Ask for the configured dimensions, if any.

        Returns:
            The settings, or ``None``.
        """
        return None if self.configured is None else EmbeddingSettings(dimensions=self.configured)

    async def dimensions(self) -> int:
        """Return the configured dimensions, or embed a fixed text once to learn them.

        Returns:
            The vectors' size.
        """
        if self.configured is not None:
            return self.configured
        if not self._probed:
            result = await self._call(self.embedder.embed_query(DIMENSIONS_PROBE))
            self._probed.append(len(result.embeddings[0]))
        return self._probed[0]

    async def embed_documents(self, texts: Sequence[str]) -> EmbeddedTexts:
        """Embed texts as documents, ``batch_size`` per call.

        Args:
            texts: The texts.

        Returns:
            One vector per text, and the tokens the provider reported.
        """
        vectors: list[tuple[float, ...]] = []
        tokens = requests = 0
        for batch in batched(texts, self.batch_size, strict=False):
            result = await self._call(
                self.embedder.embed_documents(list(batch), settings=self._settings())
            )
            if len(result.embeddings) != len(batch):
                reason = f"{len(result.embeddings)} vectors for {len(batch)} texts"
                raise EmbeddingFailedError(self.name, reason)
            vectors.extend(tuple(float(x) for x in v) for v in result.embeddings)
            tokens += result.usage.input_tokens or 0
            requests += 1
        return EmbeddedTexts(vectors=tuple(vectors), input_tokens=tokens, requests=requests)

    async def embed_query(self, text: str) -> EmbeddedTexts:
        """Embed a query as a query.

        Args:
            text: The query.

        Returns:
            Its vector, and the tokens the provider reported.
        """
        result = await self._call(self.embedder.embed_query(text, settings=self._settings()))
        return EmbeddedTexts(
            vectors=(tuple(float(x) for x in result.embeddings[0]),),
            input_tokens=result.usage.input_tokens or 0,
            requests=1,
        )

    async def _call(self, call: Awaitable[EmbeddingResult]) -> EmbeddingResult:
        """Await a call, turning any failure into ``EmbeddingFailedError``.

        Args:
            call: The call.

        Returns:
            Its result.

        Raises:
            EmbeddingFailedError: It failed; the reason names the error type and HTTP status,
                never a key (an SDK's message may echo a request).
        """
        try:
            return await call
        except _call_errors() as error:
            reason = type(error).__name__
            if isinstance(error, ModelHTTPError):
                reason = f"{reason} {error.status_code}"
            raise EmbeddingFailedError(
                self.name, reason[:MAX_EMBEDDING_ERROR], transient=_transient(error)
            ) from None
