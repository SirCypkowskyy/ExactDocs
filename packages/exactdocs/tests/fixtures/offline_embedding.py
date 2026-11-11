"""Hybrid search on the fixture docs repository without any model: an in-process embedding.

Shared by the ranking suite (``tests/retrieval/ranking``) and the retrieval eval suite
(``packages/exactdocs/evals``, ``--offline-embedding``). The embedding is the term-hash stand-in
(``HashEmbeddingModels(by_terms=True)``): each term of a text is hashed into one dimension, so
texts sharing terms are near. It checks hybrid's plumbing, its fusion and its wrong-version
guarantee; it finds no paraphrase a real model would, so its recall says nothing about whether
hybrid should become a default (docs/evals.md). No provider is ever called: the profile's
endpoint is a closed loopback port and the model factory never builds a client.

``offline_hyde_container`` adds an ``llm`` role answered by a pydantic-ai stand-in
(``TestModel`` / ``FunctionModel``), so ``hybrid_hyde`` runs end to end, priced, without a network.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from exactdocs.bootstrap.container import Container
from exactdocs.bootstrap.settings import AiSettings, Settings
from exactdocs.retrieval.adapters.driven.memory import HashEmbeddingModels
from exactdocs.retrieval.errors import ProviderUnsupportedError
from exactdocs.retrieval.models import ModelCheck, ModelRole, ProviderProfile, RetrievalMode
from exactdocs.retrieval.ports.driven import Reranker

PROFILE = "offline"
"""The provider profile of the stand-in model."""
MODEL = "term-hash"
"""The stand-in model's name, as the embedding role names it (``offline:term-hash``)."""
DIMENSIONS = 256
"""The stand-in's vector size: few enough collisions between the fixture's terms."""
LLM = "writer"
"""The stand-in LLM's name, as the ``llm`` role names it (``offline:writer``)."""
LLM_PRICE = {"input_usd_per_mtok": 1.0, "output_usd_per_mtok": 2.0}
"""The stand-in LLM's price (``[ai.prices."offline:writer"]``), so its USD is counted."""


@dataclass(frozen=True, slots=True, kw_only=True)
class MarkerFactory:
    """Implements ``ModelFactory``: builds no client; the bound stand-in ignores the handle.

    With ``chat``, the ``llm`` role's model is the pydantic-ai stand-in it returns.
    """

    chat: Callable[[], object] | None = None
    """Builds the stand-in chat model (``TestModel``, ``FunctionModel``); none: no chat model."""

    def unsupported(self, profile: ProviderProfile) -> str | None:
        """Say every profile can be called (by answering nothing).

        Args:
            profile: The profile.
        """
        del profile

    async def chat_model(self, profile: ProviderProfile, model: str) -> object:
        """Return the stand-in chat model, if there is one.

        Args:
            profile: The profile.
            model: The model.

        Returns:
            The stand-in.

        Raises:
            ProviderUnsupportedError: No stand-in chat model was given.
        """
        if self.chat is None:
            raise ProviderUnsupportedError(profile.name, model)
        return self.chat()

    async def embedder(self, profile: ProviderProfile, model: str) -> object:
        """Return a marker for the stand-in to ignore.

        Args:
            profile: The profile.
            model: The model.

        Returns:
            A plain object.
        """
        del profile, model
        return object()

    async def reranker(self, profile: ProviderProfile, model: str) -> Reranker:
        """Refuse: no reranker is offline.

        Args:
            profile: The profile.
            model: The model.

        Raises:
            ProviderUnsupportedError: Always.
        """
        raise ProviderUnsupportedError(profile.name, model)

    async def release(self, name: str) -> None:
        """Release nothing.

        Args:
            name: The profile.
        """
        del name

    async def check(self, profile: ProviderProfile, model: str, role: ModelRole) -> ModelCheck:
        """Report the stand-in as working.

        Args:
            profile: The profile.
            model: The model.
            role: The role.

        Returns:
            A passed check.
        """
        return ModelCheck(role=role, profile=profile.name, model=model, ok=True)


def offline_ai(mode: RetrievalMode | None = RetrievalMode.HYBRID) -> AiSettings:
    """Configure the stand-in as the embedding role.

    Args:
        mode: The instance's retrieval mode (hybrid is not a default, so it is named).

    Returns:
        The ``ai`` settings.
    """
    return AiSettings.model_validate(
        {
            "mode": mode,
            "providers": {
                PROFILE: {"kind": "openai-compatible", "base_url": "http://127.0.0.1:9/v1"}
            },
            "embedding": {"model": f"{PROFILE}:{MODEL}", "dimensions": DIMENSIONS},
        }
    )


def offline_container(settings: Settings) -> Container:
    """Build the app's container with the stand-in embedding model.

    Args:
        settings: The instance's settings; its ``ai`` section is replaced.

    Returns:
        The container: hybrid can run, and nothing can call a provider.
    """
    return Container.build(
        settings.model_copy(update={"ai": offline_ai()}),
        model_factory=MarkerFactory(),
        embedding_models=HashEmbeddingModels(size=DIMENSIONS, by_terms=True),
    )


def offline_data_container(data_dir: Path) -> Container:
    """Build the stand-in's container on a data directory (the eval suite's ``build``).

    Args:
        data_dir: The data directory.

    Returns:
        The container.
    """
    return offline_container(Settings(data_dir=data_dir))


def offline_hyde_container(chat: Callable[[], object]) -> Callable[[Path], Container]:
    """Build the stand-in's container with an ``llm`` role too (the eval suite's ``build``).

    Args:
        chat: Builds the pydantic-ai stand-in for the LLM (``TestModel``, ``FunctionModel``).

    Returns:
        The build function: hybrid and hybrid_hyde can run, and nothing can call a provider.
    """

    def build(data_dir: Path) -> Container:
        """Build the container on a data directory.

        Args:
            data_dir: The data directory.

        Returns:
            The container.
        """
        ai = AiSettings.model_validate(
            {
                "providers": {
                    PROFILE: {"kind": "openai-compatible", "base_url": "http://127.0.0.1:9/v1"}
                },
                "embedding": {"model": f"{PROFILE}:{MODEL}", "dimensions": DIMENSIONS},
                "llm": {"model": f"{PROFILE}:{LLM}"},
                "prices": {f"{PROFILE}:{LLM}": LLM_PRICE},
            }
        )
        return Container.build(
            Settings(data_dir=data_dir, ai=ai),
            model_factory=MarkerFactory(chat=chat),
            embedding_models=HashEmbeddingModels(size=DIMENSIONS, by_terms=True),
        )

    return build
