"""The chunk counts of a library's versions list, which need two domains (#513).

A version's article count is the catalog's (its active manifest's entries); its chunks and
embedded chunks are retrieval's. The catalog may not ask retrieval (bridges point the other way),
so the composition root lists the page through the catalog and adds retrieval's counts for the
whole page at once, as ``library_filters.ListLibrariesByAi`` adds the AI switch.
"""

from dataclasses import dataclass

from exactdocs.catalog.dtos import ListVersionsQuery, VersionList
from exactdocs.catalog.ports.driving import ListVersions
from exactdocs.retrieval.dtos import CountVersionChunksQuery
from exactdocs.retrieval.ports.driving import CountVersionChunks


@dataclass(frozen=True, slots=True, kw_only=True)
class ListVersionsWithChunks:
    """Implements the catalog's ``ListVersions`` with each version's chunk counts filled in."""

    list_versions: ListVersions
    """The catalog's use case: filters, sorts, pages and counts the articles."""
    count_version_chunks: CountVersionChunks
    """Retrieval's chunk and embedded-chunk counts of many versions, in one call."""

    async def __call__(self, query: ListVersionsQuery) -> VersionList:
        """List a page of a library's versions with their article, chunk and embedded counts.

        One call to each domain, whatever the page size: no request per version.

        Args:
            query: The library, the filters, the sort and the page.

        Returns:
            The catalog's page, each version with its chunk counts.
        """
        page = await self.list_versions(query)
        if not page.versions:
            return page
        counted = await self.count_version_chunks(
            CountVersionChunksQuery(library=page.library, refs=[v.ref for v in page.versions])
        )
        versions = [
            v
            if (found := counted.versions.get(v.ref)) is None
            else v.model_copy(
                update={"chunks": found.chunks, "embedded_chunks": found.embedded_chunks}
            )
            for v in page.versions
        ]
        return page.model_copy(update={"versions": versions})
