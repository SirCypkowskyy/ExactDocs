"""Filters of the libraries list that need two domains (`ai_enabled`, `sync_state`).

The AI switch is retrieval's data and the state of a library's latest sync ingestion's; the
catalog may not ask either (bridges point the other way), so the composition root turns each
filter into the IDs the catalog lists or skips. The catalog still filters, sorts and pages, so a
page at a cursor or an offset and its `total` come from one and the same list.
"""

from dataclasses import dataclass

from exactdocs.catalog.dtos import LibraryList, ListLibrariesQuery
from exactdocs.catalog.ports.driving import ListLibraries
from exactdocs.ingestion.dtos import SyncStatesQuery
from exactdocs.ingestion.models import JobState
from exactdocs.ingestion.ports.driving import ListLibrariesInSyncStates
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


@dataclass(frozen=True, slots=True, kw_only=True)
class ListLibrariesBySync:
    """Implements the catalog's ``ListLibraries`` with the ``sync_state`` filter applied."""

    list_libraries: ListLibraries
    """The catalog's use case (or another filter around it), which filters, sorts and pages."""
    in_sync_states: ListLibrariesInSyncStates
    """Ingestion: the libraries whose newest import job is in given states, in one query."""

    async def __call__(
        self,
        query: ListLibrariesQuery,
        *,
        only: frozenset[str] | None = None,
        without: frozenset[str] = frozenset(),
    ) -> LibraryList:
        """List a page of libraries, keeping those whose latest sync is in the states asked for.

        Args:
            query: The filters, the sort, the page size and the cursor.
            only: Case-folded library IDs; when given, no other library is listed.
            without: Case-folded library IDs that are not listed.

        Returns:
            The catalog's page.
        """
        if not query.sync_state:
            return await self.list_libraries(query, only=only, without=without)
        found = await self.in_sync_states(
            SyncStatesQuery(states=[JobState(state) for state in query.sync_state])
        )
        synced = frozenset(found.libraries)
        return await self.list_libraries(
            query, only=synced if only is None else only & synced, without=without
        )
