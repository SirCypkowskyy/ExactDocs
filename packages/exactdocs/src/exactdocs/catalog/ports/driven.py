"""Driven (secondary) ports: what the catalog needs from infrastructure."""

from collections.abc import Sequence
from typing import Protocol

from exactdocs.catalog.models import Library, LibraryId


class LibraryRepository(Protocol):
    """Persistence for catalog entries."""

    async def list_all(self) -> Sequence[Library]:
        """Return every library."""
        ...

    async def get(self, library_id: LibraryId) -> Library | None:
        """Return the library with this ID, or ``None``."""
        ...

    async def save(self, library: Library) -> None:
        """Store the library, replacing any earlier entry with the same ID."""
        ...
