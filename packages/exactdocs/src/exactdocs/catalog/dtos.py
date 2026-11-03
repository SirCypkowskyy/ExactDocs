"""Data crossing the catalog boundary (into and out of driving ports). Immutable, validated."""

from collections.abc import Iterable
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from exactdocs.catalog.models import Library


class _Dto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LibrarySummary(_Dto):
    """A library and its indexed versions, sorted ascending."""

    name: str
    versions: list[str]

    @classmethod
    def from_model(cls, library: Library) -> Self:
        """Map a domain entity to its boundary representation."""
        return cls(name=library.name, versions=[str(v) for v in sorted(library.versions)])


class LibraryList(_Dto):
    """All libraries visible to the caller, sorted by name."""

    libraries: list[LibrarySummary]

    @classmethod
    def from_models(cls, libraries: Iterable[Library]) -> Self:
        """Map domain entities."""
        ordered = sorted(libraries, key=lambda lib: lib.name)
        return cls(libraries=[LibrarySummary.from_model(lib) for lib in ordered])


class GetLibraryQuery(_Dto):
    """Look up one library by its exact name."""

    name: str = Field(min_length=1)
