"""Identity entities and value objects. Pure Python: no frameworks, no I/O."""

import hashlib
import ipaddress
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import NewType
from urllib.parse import urlsplit

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
    MAX_RETURN_TO_LENGTH,
    MAX_TOKEN_NAME_LENGTH,
    MAX_USERNAME_LENGTH,
    PROVIDER_NAME_PATTERN,
    RESERVED_IN_USERNAME,
    SIGN_IN_ATTEMPT_LIFETIME,
)
from exactdocs.identity.errors import InvalidTokenNameError, InvalidUsernameError

AccountId = NewType("AccountId", str)


class Role(StrEnum):
    """What an account may do on the instance (library roles are another matter, E12-05).

    ``admin`` is an operator: besides everything a user does, it manages the local accounts.
    The first account is always one. ``user`` signs in and uses the instance, nothing more.
    """

    ADMIN = "admin"
    USER = "user"


@dataclass(frozen=True, slots=True)  # conventions: allow-positional -- one-field value object
class Username:
    """A login name, compared case-insensitively: ``Admin`` and ``admin`` are the same account."""

    value: str
    """The name, NFKC-normalized and case-folded."""

    def __post_init__(self) -> None:
        """Normalize the name.

        Raises:
            InvalidUsernameError: The name is empty, too long or holds spaces or control
                characters.
        """
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
        """Return the normalized name.

        Returns:
            ``value``.
        """
        return self.value


@dataclass(frozen=True, slots=True, kw_only=True)
class Account:
    """An account. ``password_hash`` is an encoded KDF hash, never the password.

    An account created by an external sign-in has no password (``password_hash`` is ``None``):
    it signs in through its identity provider only.
    """

    id: AccountId
    """Stable identifier of the account."""
    username: Username
    """The login name."""
    password_hash: str | None = field(repr=False)
    """Encoded KDF hash of the password; ``None`` for an account of an identity provider."""
    role: Role
    """What the account may do."""
    created_at: datetime
    """When the account was created."""
    disabled_at: datetime | None = None
    """When an operator disabled the account; ``None`` while it may sign in."""

    @property
    def is_disabled(self) -> bool:
        """Whether the account is locked out: no sign-in, no session, no token works for it.

        Returns:
            ``True`` once an operator disabled it, until one enables it again.
        """
        return self.disabled_at is not None

    @property
    def is_external(self) -> bool:
        """Whether the account signs in through an identity provider, never with a password.

        Returns:
            ``True`` when it has no password hash.
        """
        return self.password_hash is None

    @property
    def is_operator(self) -> bool:
        """Whether the account manages the instance's local accounts.

        Returns:
            ``True`` for an ``admin``.
        """
        return self.role is Role.ADMIN


def hash_token(token: str) -> str:
    """Return the storage form of a session token.

    Tokens are 256 random bits, so a plain SHA-256 is enough (no salt or stretching, unlike a
    password): a leaked database cannot be turned back into usable tokens.

    Args:
        token: The secret token.

    Returns:
        Its SHA-256, in hex.
    """
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class Session:
    """A signed-in browser. Identified by the hash of its secret token, never by the token."""

    token_hash: str = field(repr=False)
    """SHA-256 of the session token (see ``hash_token``)."""
    account_id: AccountId
    """The signed-in account."""
    created_at: datetime
    """When the account signed in."""
    last_used_at: datetime
    """When the session last authenticated a request."""

    def expires_at(self) -> datetime:
        """When the session ends if it is not used again: idle or absolute timeout, first wins.

        Returns:
            The earlier of the idle and the absolute deadline.
        """
        return min(self.last_used_at + IDLE_TIMEOUT, self.created_at + ABSOLUTE_TIMEOUT)

    def is_expired(self, now: datetime) -> bool:
        """Whether the session is over at ``now``.

        Args:
            now: The current time.

        Returns:
            ``True`` once ``expires_at()`` has passed.
        """
        return now >= self.expires_at()


@dataclass(frozen=True, slots=True, kw_only=True)
class ApiToken:
    """A revocable credential for agents, the CLI and scripts. It acts as its account.

    Only the hash of the secret is kept; ``prefix`` (the first characters) lets a person tell
    tokens apart in a list. ``expires_at`` is ``None`` for a token that never expires.
    """

    id: str
    """Stable identifier of the token."""
    account_id: AccountId
    """The account the token acts as."""
    name: str
    """What the owner called the token, to tell it apart."""
    token_hash: str = field(repr=False)
    """SHA-256 of the secret (see ``hash_token``)."""
    prefix: str
    """The first characters of the secret, shown in lists."""
    created_at: datetime
    """When the token was created."""
    expires_at: datetime | None = None
    """When the token stops working; ``None`` for never."""
    last_used_at: datetime | None = None
    """When the token last authenticated a request; ``None`` if never used."""

    def __post_init__(self) -> None:
        """Check the name.

        Raises:
            InvalidTokenNameError: The name is blank or too long.
        """
        if not self.name.strip() or len(self.name) > MAX_TOKEN_NAME_LENGTH:
            raise InvalidTokenNameError(MAX_TOKEN_NAME_LENGTH)

    def is_expired(self, now: datetime) -> bool:
        """Whether the token no longer works at ``now``.

        Args:
            now: The current time.

        Returns:
            ``True`` when the token has an expiry and it has passed.
        """
        return self.expires_at is not None and now >= self.expires_at


@dataclass(frozen=True, slots=True, kw_only=True)
class FailedSignIns:
    """The recent failed sign-ins of one client address or of one username.

    ``previous_at`` is the ``last_at`` before the latest attempt (``None`` when that attempt
    started the count), so the attempt can be taken back without moving the wait.
    """

    count: int
    """Failures counted so far."""
    last_at: datetime
    """When the latest failure was counted."""
    previous_at: datetime | None = None
    """``last_at`` before the latest failure; ``None`` when that failure started the count."""

    def is_forgotten(self, now: datetime) -> bool:
        """Whether no failure came for long enough that the count starts over.

        Args:
            now: The current time.

        Returns:
            ``True`` when ``FORGET_FAILURES_AFTER`` has passed since ``last_at``.
        """
        return now - self.last_at >= FORGET_FAILURES_AFTER

    def plus_one(self, now: datetime) -> FailedSignIns:
        """Return the record after one more failure at ``now``.

        Args:
            now: When the failure happened.

        Returns:
            The new record; a fresh count of one when the old one is forgotten.
        """
        if self.is_forgotten(now):
            return FailedSignIns(count=1, last_at=now)
        return FailedSignIns(count=self.count + 1, last_at=now, previous_at=self.last_at)

    def wait(self, now: datetime) -> timedelta:
        """How long the next attempt must wait from ``now``.

        Args:
            now: The current time.

        Returns:
            The wait; zero when the attempt may go ahead.
        """
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

        Args:
            charged_at: The ``last_at`` the attempt being taken back was charged with.

        Returns:
            The record without that attempt, or ``None`` when no failure is left.
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


def known_sign_in_key(username: Username, address: str) -> str:
    """Return the key under which the throttle remembers that an address signed into a username.

    Args:
        username: The username signed into.
        address: The client's throttle key (``address_key``).

    Returns:
        ``<username>@address:...``.
    """
    return f"{username}@{address}"


def known_sign_ins_prefix(username: str) -> str:
    """Return what every remembered sign-in key of ``username`` starts with.

    ``address_key`` always starts with ``address:``, so every remembered sign-in of
    ``username`` starts with this, and forgetting by it never keeps one of them. It can only err
    the other way: a username that itself holds ``@address:`` (``Username`` allows one), say
    ``a@address:x``, starts with the prefix of ``a``, so forgetting ``a`` also forgets its
    remembered sign-ins. That account then becomes stricter (its attempts count against its
    username again), never more lenient. An account created by an operator cannot hold
    ``RESERVED_IN_USERNAME`` (``CreateUser`` refuses it), so it only matters for a first admin
    named that way, and the risk is too small to be worth a separate username column.

    Args:
        username: The (normalised) username.

    Returns:
        ``<username>@address:``.
    """
    return f"{username}@address:"


def address_key(client: str) -> str:
    """Return the throttle key of a client address.

    IPv4 counts per address, IPv6 per /64 (one client usually holds a whole /64, so counting per
    address would give it endless fresh counts). IPv4-mapped and NAT64 addresses count as the
    IPv4 client they carry. Anything else is used as it is.

    Args:
        client: The client address, as the transport reports it.

    Returns:
        ``address:<address or /64 network>``.
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


def safe_return_to(raw: str | None) -> str:
    """Return where to send the browser after an external sign-in: a same-origin path only.

    Anything else (an absolute URL, ``//host``, a backslash, a control character, the sign-in
    page itself) becomes ``/``, so the sign-in can never be used as an open redirect.

    Args:
        raw: The path the sign-in was started with, if any.

    Returns:
        ``raw`` when it is a path on this server, else ``/``.
    """
    if (
        not raw
        or not raw.startswith("/")
        or raw.startswith("//")
        or len(raw) > MAX_RETURN_TO_LENGTH
    ):
        return "/"
    if any(c == "\\" or unicodedata.category(c).startswith("C") for c in raw):
        return "/"
    parts = urlsplit(raw)
    if parts.scheme or parts.netloc or parts.path in {"/sign-in", "/setup"}:
        return "/"
    return raw


@dataclass(frozen=True, slots=True, kw_only=True)
class SignInPolicy:
    """Who a sign-in provider admits, with which role and groups, and for how long.

    ``allowed_groups`` and ``admin_groups`` name groups as the identity provider sends them;
    ``group_prefix`` only changes the name ExactDocs stores. Only ``allowed_groups`` (or
    ``allow_any_user``) admits anyone: an admin group decides the role of who is admitted.
    """

    name: str
    """The provider's name (``[a-z0-9-]``): in URLs and in the ``<username>@<name>`` fallback."""
    display_name: str
    """What the sign-in button says."""
    allowed_groups: frozenset[str] = frozenset()
    """Groups whose members may sign in."""
    allow_any_user: bool = False
    """Admit everyone the provider vouches for; required when ``allowed_groups`` is empty."""
    admin_groups: frozenset[str] = frozenset()
    """Groups whose members are ``admin`` (else ``user``), at every sign-in and revalidation."""
    group_prefix: str = ""
    """Put before each stored group name (``corp:`` stores ``payments`` as ``corp:payments``)."""
    revalidate_every: timedelta
    """How often memberships are checked again with the stored refresh token."""
    grace: timedelta
    """How long access lasts without a successful check: the provider unreachable, or no
    refresh token at all."""

    def __post_init__(self) -> None:
        """Check the name and that the policy admits someone on purpose.

        Raises:
            ValueError: The name is not ``[a-z0-9-]``, nobody is admitted without
                ``allow_any_user``, or a duration is not positive.
        """
        if not re.fullmatch(PROVIDER_NAME_PATTERN, self.name):
            message = f"sign-in provider name {self.name!r} must match {PROVIDER_NAME_PATTERN}"
            raise ValueError(message)
        if not self.allowed_groups and not self.allow_any_user:
            message = f"sign-in provider {self.name!r}: set allowed_groups or allow_any_user"
            raise ValueError(message)
        if self.revalidate_every <= timedelta(0) or self.grace <= timedelta(0):
            message = f"sign-in provider {self.name!r}: revalidation times must be positive"
            raise ValueError(message)

    def admits(self, groups: Iterable[str]) -> bool:
        """Whether someone in ``groups`` may sign in.

        Args:
            groups: The person's groups, as the provider names them.

        Returns:
            ``True`` with ``allow_any_user``, or when one of the groups is allowed.
        """
        return self.allow_any_user or bool(self.allowed_groups.intersection(groups))

    def role_for(self, groups: Iterable[str]) -> Role:
        """Return the role of someone in ``groups``.

        Args:
            groups: The person's groups, as the provider names them.

        Returns:
            ``admin`` while one of them is an admin group, else ``user``.
        """
        return Role.ADMIN if self.admin_groups.intersection(groups) else Role.USER

    def stored_groups(self, groups: Iterable[str]) -> frozenset[str]:
        """Return the ExactDocs group names of ``groups`` (``group_prefix`` put before each).

        Args:
            groups: The person's groups, as the provider names them.

        Returns:
            The names to store.
        """
        return frozenset(f"{self.group_prefix}{group}" for group in groups)

    def access_until(self, now: datetime, *, refreshable: bool) -> datetime:
        """Return until when a check at ``now`` grants access.

        Args:
            now: When the memberships were checked.
            refreshable: Whether a refresh token lets them be checked again later.

        Returns:
            ``now`` plus the revalidation interval and the grace when refreshable; without a
            refresh token nothing can check again, so only the grace.
        """
        if refreshable:
            return now + self.revalidate_every + self.grace
        return now + self.grace


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalClaims:
    """Who an identity provider says signed in, already validated by the provider's adapter."""

    issuer: str
    """The issuer (an OIDC provider's ``iss``): with ``subject``, the person's stable identity."""
    subject: str
    """The person's identifier at the issuer (``sub``), never reassigned."""
    username: str | None = None
    """The preferred login name, if the provider sends one (only used to name a new account)."""
    email: str | None = None
    """The email address, if the provider sends one (only its local part names an account)."""
    groups: frozenset[str] = frozenset()
    """The person's groups, as the provider names them."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalGrant:
    """What a successful code exchange or refresh gives: the claims and a refresh token."""

    claims: ExternalClaims
    """Who signed in, and their groups."""
    refresh_token: str | None = field(default=None, repr=False)
    """Lets the memberships be checked again later; ``None`` when the provider issued none."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalIdentity:
    """An identity at a provider, linked to one account by (issuer, subject) and nothing else."""

    issuer: str
    """The provider's issuer."""
    subject: str
    """The person's identifier at the issuer."""
    account_id: AccountId
    """The linked account."""
    provider: str
    """The configured provider it signed in through (its name)."""
    sealed_tokens: str | None = field(default=None, repr=False)
    """The refresh token, sealed by the secret box; ``None`` when there is none (or it was
    revoked)."""
    signed_in_at: datetime
    """The latest sign-in through the provider."""
    checked_at: datetime
    """The latest successful check of the memberships (a sign-in or a revalidation)."""
    next_check_at: datetime
    """When the memberships are due to be checked again."""
    access_until: datetime
    """Sessions and API tokens of the account are refused from then on, until a sign-in or a
    revalidation moves it forward."""

    def has_access(self, now: datetime) -> bool:
        """Whether the account may be used at ``now``.

        Args:
            now: The current time.

        Returns:
            ``True`` before ``access_until``.
        """
        return now < self.access_until


@dataclass(frozen=True, slots=True, kw_only=True)
class SignInAttempt:
    """An external sign-in that was started and has not come back yet. Usable once.

    Kept in the database, so the callback may reach another process than the start did.
    """

    binding_hash: str = field(repr=False)
    """SHA-256 of the random value in the browser's binding cookie (see ``hash_token``)."""
    provider: str
    """The provider the sign-in was started with."""
    state: str = field(repr=False)
    """Must come back unchanged from the provider."""
    nonce: str = field(repr=False)
    """Must be in the ID token."""
    code_verifier: str = field(repr=False)
    """The PKCE verifier; the provider saw only its S256 challenge."""
    return_to: str
    """Where the browser goes once signed in (a same-origin path)."""
    created_at: datetime
    """When the sign-in was started."""

    def is_expired(self, now: datetime) -> bool:
        """Whether the attempt came back too late.

        Args:
            now: The current time.

        Returns:
            ``True`` once ``SIGN_IN_ATTEMPT_LIFETIME`` has passed since it started.
        """
        return now >= self.created_at + SIGN_IN_ATTEMPT_LIFETIME


def username_candidates(claims: ExternalClaims, provider: str) -> list[Username]:
    """Return the usernames a first external sign-in may take, in order.

    The provider's username, else the local part of the email; then the same with ``@<provider>``
    after it. A name holding ``RESERVED_IN_USERNAME``, or not a valid username, is skipped.

    Args:
        claims: Who signed in.
        provider: The provider's name.

    Returns:
        The candidates, best first; empty when the provider sent nothing usable.
    """
    base = claims.username or (claims.email.partition("@")[0] if claims.email else None)
    if not base:
        return []
    candidates: list[Username] = []
    for name in (base, f"{base}@{provider}"):
        try:
            username = Username(name)
        except InvalidUsernameError:
            continue
        if RESERVED_IN_USERNAME not in username.value and username not in candidates:
            candidates.append(username)
    return candidates
