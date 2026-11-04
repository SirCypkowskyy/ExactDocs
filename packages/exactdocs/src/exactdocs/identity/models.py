"""Identity entities and value objects. Pure Python: no frameworks, no I/O."""

import hashlib
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import NewType

from exactdocs.identity.errors import InvalidTokenNameError, InvalidUsernameError

AccountId = NewType("AccountId", str)

MAX_USERNAME_LENGTH = 64
MAX_TOKEN_NAME_LENGTH = 64
VALUE_PREFIX = "exd_"  # recognizable, so secret scanners and humans can spot a leaked token
PREFIX_SHOWN = len(VALUE_PREFIX) + 4  # the part of a token kept readable, to tell tokens apart
IDLE_TIMEOUT = timedelta(days=7)  # a session unused for this long ends
ABSOLUTE_TIMEOUT = timedelta(days=30)  # and none lives longer than this, however busy


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


def hash_token(token: str) -> str:
    """Return the storage form of a session token.

    Tokens are 256 random bits, so a plain SHA-256 is enough (no salt or stretching, unlike a
    password): a leaked database cannot be turned back into usable tokens.
    """
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class Session:
    """A signed-in browser. Identified by the hash of its secret token, never by the token."""

    token_hash: str = field(repr=False)
    account_id: AccountId
    created_at: datetime
    last_used_at: datetime

    def expires_at(self) -> datetime:
        """When the session ends if it is not used again: idle or absolute timeout, first wins."""
        return min(self.last_used_at + IDLE_TIMEOUT, self.created_at + ABSOLUTE_TIMEOUT)

    def is_expired(self, now: datetime) -> bool:
        """Whether the session is over at ``now``."""
        return now >= self.expires_at()


@dataclass(frozen=True, slots=True, kw_only=True)
class ApiToken:
    """A revocable credential for agents, the CLI and scripts. It acts as its account.

    Only the hash of the secret is kept; ``prefix`` (the first characters) lets a person tell
    tokens apart in a list. ``expires_at`` is ``None`` for a token that never expires.
    """

    id: str
    account_id: AccountId
    name: str
    token_hash: str = field(repr=False)
    prefix: str
    created_at: datetime
    expires_at: datetime | None = None
    last_used_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.name.strip() or len(self.name) > MAX_TOKEN_NAME_LENGTH:
            raise InvalidTokenNameError(MAX_TOKEN_NAME_LENGTH)

    def is_expired(self, now: datetime) -> bool:
        """Whether the token no longer works at ``now``."""
        return self.expires_at is not None and now >= self.expires_at
