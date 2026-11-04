"""Driven (secondary) ports of retrieval."""

from collections.abc import Sequence
from typing import Protocol

from exactdocs.retrieval.models import DocTarget, Excerpt, SearchText


class IndexedVersions(Protocol):
    """Which library versions have an index.

    The catalog domain owns this knowledge. Retrieval states what it needs in its own terms
    and the composition root plugs in an adapter, so neither domain imports the other.
    """

    async def find_indexed(self, target: DocTarget) -> DocTarget | None:
        """Return ``target`` in its canonical spelling, or ``None`` unless that version exists.

        Canonical means the library ID as stored (`/Acme/Payments` is `/acme/payments`); the
        version is never altered or approximated.
        """
        ...


class ExcerptIndex(Protocol):
    """Search backend (BM25 + vectors + rerank) scoped to one library version."""

    async def search(self, target: DocTarget, text: SearchText, limit: int) -> Sequence[Excerpt]:
        """Return at most ``limit`` excerpts from ``target`` only, best first."""
        ...
