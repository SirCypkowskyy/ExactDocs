"""Driving (primary) ports of retrieval."""

from typing import Protocol

from exactdocs.retrieval.dtos import SearchDocsQuery, SearchDocsResult


class SearchDocs(Protocol):
    """Hybrid search within one library version; raises ``VersionNotIndexedError``."""

    async def __call__(self, query: SearchDocsQuery) -> SearchDocsResult:
        """Run the use case."""
        ...
