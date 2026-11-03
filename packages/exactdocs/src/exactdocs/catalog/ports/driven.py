"""Driven (secondary) ports: what the catalog needs from infrastructure."""

from collections.abc import Sequence
from typing import Protocol

from exactdocs.catalog.models import Library, LibraryName


class LibraryRepository(Protocol):
    """Persistence for catalog entries."""

    async def list_all(self) -> Sequence[Library]:
        """Return every library."""
        ...

    async def get(self, name: LibraryName) -> Library | None:
        """Return the library with this exact name, or ``None``."""
        ...

    async def save(self, library: Library) -> None:
        """Store the library, replacing any earlier entry with the same name."""
        ...
