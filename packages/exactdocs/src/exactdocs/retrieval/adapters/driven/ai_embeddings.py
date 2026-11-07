"""Implements retrieval's ``EmbeddingModels`` with pydantic-ai, imported only when called.

This module is light: it imports no SDK, so a process with no embedding model configured never
loads pydantic-ai. ``bind`` loads ``ai_embeddings_sdk`` (pydantic-ai's ``Embedder``, the
``[ai]`` extra) the first time a configured embedding model is called.
"""

import importlib
from dataclasses import dataclass

from exactdocs.retrieval.constants import EMBEDDINGS_SDK_MODULE
from exactdocs.retrieval.ports.driven import Embeddings


@dataclass(frozen=True, slots=True, kw_only=True)
class PydanticAiEmbeddingModels:
    """Implements ``ports.driven.EmbeddingModels`` over the ``Embedder`` the factory built."""

    def bind(
        self, handle: object, *, name: str, dimensions: int | None, batch_size: int
    ) -> Embeddings:
        """Wrap a pydantic-ai ``Embedder``.

        Args:
            handle: What ``ModelFactory.embedder`` returned.
            name: ``<profile>:<model>``.
            dimensions: The configured dimensions, if any.
            batch_size: The most texts per call.

        Returns:
            The model.
        """
        sdk = importlib.import_module(EMBEDDINGS_SDK_MODULE)
        return sdk.wrap(handle, name=name, dimensions=dimensions, batch_size=batch_size)
