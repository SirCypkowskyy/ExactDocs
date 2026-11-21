"""Filters of the libraries list that need two domains (`ai_enabled`).

The AI switch is retrieval's data and the catalog may not ask retrieval for it (bridges point
the other way), so the composition root turns the filter into the IDs the catalog lists or skips.
"""

from dataclasses import dataclass

from exactdocs.catalog.dtos import LibraryList, ListLibrariesQuery
from exactdocs.catalog.ports.driving import ListLibraries
from exactdocs.retrieval.ports.driven import LibraryModes


@dataclass(frozen=True, slots=True, kw_only=True)
class ListLibrariesByAi:
    """Implements the catalog's ``ListLibraries`` with the ``ai_enabled`` filter applied."""

    list_libraries: ListLibraries
    """The catalog's use case, which filters, sorts and pages."""
    settings: LibraryModes
    """Where retrieval keeps each library's AI switch."""

    async def __call__(
        self,
        query: ListLibrariesQuery,
        *,
        only: frozenset[str] | None = None,
        without: frozenset[str] = frozenset(),
    ) -> LibraryList:
        """List a page of libraries, keeping those with AI on or off when the query asks.

        Args:
            query: The filters, the sort, the page size and the cursor.
            only: Case-folded library IDs; when given, no other library is listed.
            without: Case-folded library IDs that are not listed.

        Returns:
            The catalog's page.
        """
        if query.ai_enabled is None:
            return await self.list_libraries(query, only=only, without=without)
        off = await self.settings.ai_disabled()
        if query.ai_enabled:
            return await self.list_libraries(query, only=only, without=without | off)
        return await self.list_libraries(
            query, only=off if only is None else only & off, without=without
        )
