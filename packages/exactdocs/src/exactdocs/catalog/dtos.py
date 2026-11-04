"""Data crossing the catalog boundary (into and out of driving ports). Immutable, validated."""

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field

from exactdocs.catalog.models import Library
from exactdocs_kernel import DEFAULT_LIMIT, MAX_LIMIT, Page


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


Limit = Annotated[int, Field(ge=1, le=MAX_LIMIT)]


class ListLibrariesQuery(_Dto):
    """One page of libraries: ``limit`` items after the opaque ``cursor`` of the previous page."""

    limit: Limit = DEFAULT_LIMIT
    cursor: str | None = None


class LibraryList(_Dto):
    """A page of the libraries visible to the caller, sorted by name."""

    libraries: list[LibrarySummary]
    next_cursor: str | None = Field(
        description="Pass as `cursor` to get the next page; null on the last page."
    )

    @classmethod
    def from_page(cls, page: Page[Library]) -> Self:
        """Map a page of domain entities."""
        return cls(
            libraries=[LibrarySummary.from_model(lib) for lib in page.items],
            next_cursor=page.next_cursor,
        )


class GetLibraryQuery(_Dto):
    """Look up one library by its exact name."""

    name: str = Field(min_length=1)
