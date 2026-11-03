from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Self

from exactdocs.catalog.models import Library, LibraryName


@dataclass(slots=True)
class InMemoryLibraryRepository:
    """Implements ``ports.driven.LibraryRepository``. For tests."""

    libraries: dict[LibraryName, Library] = field(default_factory=dict)

    @classmethod
    def of(cls, libraries: Iterable[Library]) -> Self:
        """Create a repository pre-filled with ``libraries``."""
        return cls({lib.name: lib for lib in libraries})

    async def list_all(self) -> Sequence[Library]:
        """Return every library."""
        return tuple(self.libraries.values())

    async def get(self, name: LibraryName) -> Library | None:
        """Return the library with this exact name, or ``None``."""
        return self.libraries.get(name)

    async def save(self, library: Library) -> None:
        """Store the library, replacing any earlier entry with the same name."""
        self.libraries[library.name] = library
