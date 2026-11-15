"""A stand-in for the library roles of catalog, ingestion and retrieval: one fixed caller."""

from collections.abc import Collection
from dataclasses import dataclass, field
from enum import StrEnum

ROLES = ("viewer", "contributor", "admin", "creator")
"""The library roles, lowest first."""


@dataclass
class FakeAccess:
    """Matches every domain's ``AccessPolicy``: the caller holds ``role`` on every library."""

    role: str | None = None
    """The caller's role everywhere; ``None``: none."""
    claimed: list[str] = field(default_factory=list)
    """The libraries whose creator the caller became."""
    forgotten: list[str] = field(default_factory=list)
    """The libraries whose grants were dropped."""

    asked: list[tuple[str, str]] = field(default_factory=list)
    """Each check made: the library and the role it needed."""

    async def allows(self, library: str, access: StrEnum) -> bool:
        self.asked.append((library, access.value))
        return self.role is not None and ROLES.index(self.role) >= ROLES.index(access.value)

    async def readable(self, libraries: Collection[str]) -> frozenset[str]:
        if self.role is None:
            return frozenset()
        return frozenset(library.casefold() for library in libraries)

    async def claim(self, library: str) -> None:
        self.claimed.append(library)

    async def forget(self, library: str) -> None:
        self.forgotten.append(library)
