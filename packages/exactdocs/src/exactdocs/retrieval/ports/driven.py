"""Driven (secondary) ports of retrieval."""

from collections.abc import Sequence
from typing import Protocol

from exactdocs.retrieval.models import DocTarget, Excerpt, SearchText


class IndexedVersions(Protocol):
    """Which library versions have an index.

    The catalog domain owns this knowledge. Retrieval states what it needs in its own terms
    and the composition root plugs in an adapter, so neither domain imports the other.
    """

    async def is_indexed(self, target: DocTarget) -> bool:
        """Return ``True`` only for an exact library and version match."""
        ...


class ExcerptIndex(Protocol):
    """Search backend (BM25 + vectors + rerank) scoped to one library version."""

    async def search(self, target: DocTarget, text: SearchText, limit: int) -> Sequence[Excerpt]:
        """Return at most ``limit`` excerpts from ``target`` only, best first."""
        ...
