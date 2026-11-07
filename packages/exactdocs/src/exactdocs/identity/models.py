"""Identity entities and value objects. Pure Python: no frameworks, no I/O."""

import hashlib
import ipaddress
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import NewType

from exactdocs.identity.constants import (
    _IPV6_NETWORK_BITS,
    _MAX_DOUBLINGS,
    _NAT64,
    ABSOLUTE_TIMEOUT,
    FIRST_WAIT,
    FORGET_FAILURES_AFTER,
    FREE_FAILURES,
    IDLE_TIMEOUT,
    LONGEST_WAIT,
    MAX_TOKEN_NAME_LENGTH,
    MAX_USERNAME_LENGTH,
)
from exactdocs.identity.errors import InvalidTokenNameError, InvalidUsernameError

AccountId = NewType("AccountId", str)


class Role(StrEnum):
    """What an account may do. Only ``admin`` exists until more users arrive (ACL-06)."""

    ADMIN = "admin"


@dataclass(frozen=True, slots=True)  # conventions: allow-positional -- one-field value object
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
    """The recent failed sign-ins of one client address or of one username.

    ``previous_at`` is the ``last_at`` before the latest attempt (``None`` when that attempt
    started the count), so the attempt can be taken back without moving the wait.
    """

    count: int
    last_at: datetime
    previous_at: datetime | None = None

    def is_forgotten(self, now: datetime) -> bool:
        """Whether no failure came for long enough that the count starts over."""
        return now - self.last_at >= FORGET_FAILURES_AFTER

    def plus_one(self, now: datetime) -> FailedSignIns:
        """Return the record after one more failure at ``now``."""
        if self.is_forgotten(now):
            return FailedSignIns(count=1, last_at=now)
        return FailedSignIns(count=self.count + 1, last_at=now, previous_at=self.last_at)

    def wait(self, now: datetime) -> timedelta:
        """How long the next attempt must wait from ``now`` (zero when it may go ahead)."""
        if self.count < FREE_FAILURES or self.is_forgotten(now):
            return timedelta(0)
        doublings = min(self.count - FREE_FAILURES, _MAX_DOUBLINGS)
        until = self.last_at + min(FIRST_WAIT * 2**doublings, LONGEST_WAIT)
        return max(until - now, timedelta(0))

    def refunded(self, charged_at: datetime) -> FailedSignIns | None:
        """Return the record with the attempt charged at ``charged_at`` taken back.

        When that attempt is still the latest, the record goes back to how it was before it
        (``None`` when it started the count), so a right password does not restart the wait.
        When a later attempt came since, only the count goes down.
        """
        if self.last_at == charged_at:
            if self.previous_at is None or self.count <= 1:
                return None
            return FailedSignIns(count=self.count - 1, last_at=self.previous_at)
        if self.count <= 1:
            return None
        return FailedSignIns(
            count=self.count - 1, last_at=self.last_at, previous_at=self.previous_at
        )


def address_key(client: str) -> str:
    """Return the throttle key of a client address.

    IPv4 counts per address, IPv6 per /64 (one client usually holds a whole /64, so counting per
    address would give it endless fresh counts). IPv4-mapped and NAT64 addresses count as the
    IPv4 client they carry. Anything else is used as it is.
    """
    try:
        ip = ipaddress.ip_address(client)
    except ValueError:
        return f"address:{client}"
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:  # ::ffff:a.b.c.d is the IPv4 client a.b.c.d
            return f"address:{ip.ipv4_mapped}"
        if ip in _NAT64:  # 64:ff9b::a.b.c.d is the IPv4 client a.b.c.d
            return f"address:{ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)}"
        return f"address:{ipaddress.ip_network((ip, _IPV6_NETWORK_BITS), strict=False)}"
    return f"address:{ip}"
