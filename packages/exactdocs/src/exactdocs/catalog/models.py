"""Catalog entities and value objects. Pure Python: no frameworks, no I/O."""

from dataclasses import dataclass, field
from typing import NewType

from exactdocs.catalog.errors import EmptyVersionError

LibraryName = NewType("LibraryName", str)


@dataclass(frozen=True, slots=True, order=True)
class Version:
    """A documentation version label exactly as published by the library (e.g. ``19.1``)."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise EmptyVersionError

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True, kw_only=True)
class Library:
    """A documented library and the versions that have an index."""

    name: LibraryName
    versions: frozenset[Version] = field(default_factory=frozenset)

    def has_version(self, version: Version) -> bool:
        """Version is a hard filter: only an exact match counts."""
        return version in self.versions
