"""The sources file's library title and description, stored through the catalog.

Composed here, outside ``bridges.py``: the port takes and returns plain values, so the class has
no ingestion model to import and the bridge-direction test could not read an edge from it.
"""

from dataclasses import dataclass

from exactdocs.catalog.dtos import UpdateLibraryCommand
from exactdocs.catalog.ports.driving import UpdateLibrary


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogLibraryTexts:
    """Implements ``ingestion.ports.driven.LibraryTexts`` using the catalog."""

    update_library: UpdateLibrary
    """The catalog's edit of a library's title and description (kept across imports)."""

    async def save(self, library: str, *, title: str | None, description: str | None) -> None:
        """Store the text the way ``PATCH /libraries/{owner}/{repo}`` does.

        Args:
            library: The library ID.
            title: The new title; ``None``: unchanged.
            description: The new description; ``None``: unchanged.
        """
        await self.update_library(
            UpdateLibraryCommand(id=library, title=title, description=description)
        )
