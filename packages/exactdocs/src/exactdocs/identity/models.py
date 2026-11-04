"""Identity entities and value objects. Pure Python: no frameworks, no I/O."""

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import NewType

from exactdocs.identity.errors import InvalidUsernameError

AccountId = NewType("AccountId", str)

MAX_USERNAME_LENGTH = 64


class Role(StrEnum):
    """What an account may do. Only ``admin`` exists until more users arrive (ACL-06)."""

    ADMIN = "admin"


@dataclass(frozen=True, slots=True)
class Username:
    """A login name, compared case-insensitively: ``Admin`` and ``admin`` are the same account."""

    value: str

    def __post_init__(self) -> None:
        # Frozen dataclass: normalise through object.__setattr__ so every instance is canonical.
        nfkc = unicodedata.normalize
        normalized = nfkc("NFKC", nfkc("NFKC", self.value).strip().casefold())  # Unicode D145
        invalid = (
            not normalized
            or len(normalized) > MAX_USERNAME_LENGTH
            or any(c.isspace() or unicodedata.category(c).startswith("C") for c in normalized)
        )
        if invalid:
            raise InvalidUsernameError(MAX_USERNAME_LENGTH)
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True, kw_only=True)
class Account:
    """A local account. ``password_hash`` is an encoded KDF hash, never the password."""

    id: AccountId
    username: Username
    password_hash: str = field(repr=False)
    role: Role
    created_at: datetime
