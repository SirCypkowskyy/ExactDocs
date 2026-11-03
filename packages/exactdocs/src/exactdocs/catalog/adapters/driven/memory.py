from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Self

from exactdocs.catalog.models import Library, LibraryName, Version


@dataclass(slots=True)
class InMemoryLibraryRepository:
    """Implements ``ports.driven.LibraryRepository``. For tests and the zero-config demo."""

    libraries: dict[LibraryName, Library] = field(default_factory=dict)

    @classmethod
    def of(cls, libraries: Iterable[Library]) -> Self:
        """Create a repository pre-filled with ``libraries``."""
        return cls({lib.name: lib for lib in libraries})

    @classmethod
    def demo(cls) -> Self:
        """Create a small fixed catalog, so a fresh install has something to show."""
        return cls.of(
            [
                Library(
                    name=LibraryName("/fastapi/fastapi"), versions=frozenset({Version("0.115")})
                ),
                Library(
                    name=LibraryName("/reactjs/react.dev"), versions=frozenset({Version("19.1")})
                ),
            ]
        )

    async def list_all(self) -> Sequence[Library]:
        """Return every library."""
        return tuple(self.libraries.values())

    async def get(self, name: LibraryName) -> Library | None:
        """Return the library with this exact name, or ``None``."""
        return self.libraries.get(name)
