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
# Sign-in throttle, counted apart per client address and per username: this many failures are
# free, then each one more doubles the wait before the next attempt, from FIRST_WAIT up to
# LONGEST_WAIT. Failures are forgotten once none came for FORGET_FAILURES_AFTER.
FREE_FAILURES = 5
FIRST_WAIT = timedelta(seconds=5)
LONGEST_WAIT = timedelta(minutes=15)
FORGET_FAILURES_AFTER = timedelta(hours=1)
_MAX_DOUBLINGS = 8  # FIRST_WAIT * 2**8 is past LONGEST_WAIT; also keeps the arithmetic small


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


@dataclass(frozen=True, slots=True, kw_only=True)
class FailedSignIns:
    """The recent failed sign-ins of one client address or of one username."""

    count: int
    last_at: datetime

    def is_forgotten(self, now: datetime) -> bool:
        """Whether no failure came for long enough that the count starts over."""
        return now - self.last_at >= FORGET_FAILURES_AFTER

    def plus_one(self, now: datetime) -> FailedSignIns:
        """Return the record after one more failure at ``now``."""
        count = 1 if self.is_forgotten(now) else self.count + 1
        return FailedSignIns(count=count, last_at=now)

    def wait(self, now: datetime) -> timedelta:
        """How long the next attempt must wait from ``now`` (zero when it may go ahead)."""
        if self.count < FREE_FAILURES or self.is_forgotten(now):
            return timedelta(0)
        doublings = min(self.count - FREE_FAILURES, _MAX_DOUBLINGS)
        until = self.last_at + min(FIRST_WAIT * 2**doublings, LONGEST_WAIT)
        return max(until - now, timedelta(0))
