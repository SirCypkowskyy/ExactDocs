"""Library roles for a process the owner runs: nobody is refused (``serve --stdio``)."""

from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenAccess:
    """Implements the ``AccessPolicy`` ports of catalog, ingestion and retrieval with no roles."""

    async def allows(self, library: str, access: StrEnum) -> bool:
        """Allow everything.

        Args:
            library: The library ID.
            access: The role the action needs.

        Returns:
            Always ``True``.
        """
        del library, access
        return True

    async def readable(self, libraries: Collection[str]) -> frozenset[str]:
        """Allow reading every library.

        Args:
            libraries: Library IDs.

        Returns:
            All of them, lower-case.
        """
        return frozenset(library.casefold() for library in libraries)

    async def claim(self, library: str) -> None:
        """Record nobody as the creator.

        Args:
            library: The library ID.
        """
        del library

    async def forget(self, library: str) -> None:
        """Forget nothing: nothing was recorded.

        Args:
            library: The library ID.
        """
        del library
