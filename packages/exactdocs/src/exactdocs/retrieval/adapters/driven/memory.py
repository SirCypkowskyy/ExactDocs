from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Self

from exactdocs.retrieval.models import DocTarget, Excerpt, SearchText


@dataclass(slots=True)
class InMemoryExcerptIndex:
    """Implements ``ports.driven.ExcerptIndex`` with case-insensitive substring matching.

    Placeholder until the SQLite (FTS5 + sqlite-vec) and pgvector adapters land.
    """

    excerpts: list[Excerpt] = field(default_factory=list)

    @classmethod
    def of(cls, excerpts: Iterable[Excerpt]) -> Self:
        """Create an index pre-filled with ``excerpts``."""
        return cls(list(excerpts))

    async def search(self, target: DocTarget, text: SearchText, limit: int) -> Sequence[Excerpt]:
        """Return excerpts of ``target`` that contain ``text``."""
        needle = text.value.casefold()
        hits = (e for e in self.excerpts if e.target == target and needle in e.text.casefold())
        return [hit for _, hit in zip(range(limit), hits, strict=False)]
