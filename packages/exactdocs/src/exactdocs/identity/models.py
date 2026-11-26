"""Identity entities and value objects. Pure Python: no frameworks, no I/O."""

import hashlib
import ipaddress
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal, NewType
from urllib.parse import urlsplit

from exactdocs.identity.constants import (
    _IPV6_NETWORK_BITS,
    _MAX_DOUBLINGS,
    _NAT64,
    ABSOLUTE_TIMEOUT,
    ACCESS_LOGOUT_PATH,
    ACCESS_PROVIDER,
    FIRST_WAIT,
    FORGET_FAILURES_AFTER,
    FREE_FAILURES,
    GITHUB_ORG_PATTERN,
    GITHUB_TEAM_PATTERN,
    IDLE_TIMEOUT,
    LONGEST_WAIT,
    MAX_RETURN_TO_LENGTH,
    MAX_TOKEN_NAME_LENGTH,
    MAX_USERNAME_LENGTH,
    PROVIDER_NAME_PATTERN,
    RESERVED_IN_USERNAME,
    SIGN_IN_ATTEMPT_LIFETIME,
    TEXT_SCALES,
)
from exactdocs.identity.errors import (
    InvalidPreferencesError,
    InvalidRoleRuleError,
    InvalidTokenNameError,
    InvalidUsernameError,
)
from exactdocs_kernel import LIBRARY_ID_PATTERN

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
    last_active_at: datetime | None = None
    """The hour (UTC, see ``activity_hour``) of the account's latest sign-in or authenticated
    request; ``None`` while it was never active (or not since activity was recorded)."""

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

    def activity_due(self, now: datetime) -> bool:
        """Whether activity at ``now`` moves the recorded hour forward (once per hour at most).

        Args:
            now: When the account was active.

        Returns:
            ``True`` when ``now`` falls in a later hour than the recorded one, or none is.
        """
        return self.last_active_at is None or self.last_active_at < activity_hour(now)

    @property
    def is_operator(self) -> bool:
        """Whether the account manages the instance's local accounts.

        Returns:
            ``True`` for an ``admin``.
        """
        return self.role is Role.ADMIN


def activity_hour(moment: datetime) -> datetime:
    """Return the hour an account's activity is recorded as: kept to the hour, for privacy.

    Args:
        moment: A timezone-aware time.

    Returns:
        The start of its hour, in UTC.
    """
    return moment.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


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

    library_ids: frozenset[str] | None = None
    """Optional library selection; ``None`` allows every library the account can access."""

    def __post_init__(self) -> None:
        """Check the name.

        Raises:
            InvalidTokenNameError: The name is blank or too long.
        """
        if self.library_ids is not None:
            object.__setattr__(
                self, "library_ids", frozenset(v.casefold() for v in self.library_ids)
            )
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


class BuiltInIcon(StrEnum):
    """An icon the web UI ships for a well-known provider; named, never served by ExactDocs."""

    DISCORD = "discord"
    GITHUB = "github"
    GOOGLE = "google"
    MICROSOFT = "microsoft"


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderIcon:
    """An operator's own icon for a sign-in provider, checked and sanitised when it was read.

    ExactDocs serves it from its own origin; ``version`` changes with the content, so a URL that
    carries it may be cached.
    """

    media_type: str
    """``image/png``, ``image/webp`` or ``image/svg+xml``."""
    content: bytes = field(repr=False)
    """The file's bytes (an SVG's rebuilt from the allowlist)."""

    @property
    def version(self) -> str:
        """A short digest of the content.

        Returns:
            The first 16 hex digits of its SHA-256.
        """
        return hashlib.sha256(self.content).hexdigest()[:16]


@dataclass(frozen=True, slots=True, kw_only=True)
class SignInPolicy:
    """Who a sign-in provider admits, with which role and groups, and for how long.

    ``allowed_groups`` and ``admin_groups`` name groups as the identity provider sends them;
    ``group_prefix`` only changes the name ExactDocs stores. Only ``allowed_groups`` (or
    ``allow_any_user``) admits anyone: an admin group decides the role of who is admitted.
    With ``auto_create_users`` off, only identities linked to an account already sign in (people
    link them from Account settings); nobody gets a new account through the provider.
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
    auto_create_users: bool = True
    """Create the account of an identity's first sign-in; when off, only linked identities sign
    in."""
    icon: BuiltInIcon | None = None
    """The built-in icon its buttons show; ``None`` for none (or for ``icon_file``)."""
    icon_file: ProviderIcon | None = None
    """The operator's own icon, served by ExactDocs; not together with ``icon``."""
    github: bool = False
    """Whether the provider is GitHub, whose organizations and teams rules may name."""
    rules: tuple[RoleRule, ...] = ()
    """The role rules the configuration file sets for this provider (``admin_groups`` apart)."""
    configured_rules_only: bool = False
    """Only the configuration file's rules apply to this provider; stored ones are ignored."""

    def __post_init__(self) -> None:
        """Check the name, that the policy admits someone on purpose, and its one icon.

        Raises:
            ValueError: The name is not ``[a-z0-9-]``, nobody is admitted without
                ``allow_any_user``, a duration is not positive, or both icons are set.
        """
        if self.icon is not None and self.icon_file is not None:
            message = f"sign-in provider {self.name!r}: set icon or icon_file, not both"
            raise ValueError(message)
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

    @property
    def configured_role_rules(self) -> tuple[RoleRule, ...]:
        """The configuration file's rules: ``admin_groups`` first, then ``rules``.

        Returns:
            The rules, read-only (``configured``).
        """
        admins = tuple(
            RoleRule(
                id=f"config:{self.name}:admin_groups:{group}",
                provider=self.name,
                source=RuleSource.GROUP,
                value=group,
                grant=RuleGrant.INSTANCE_ADMIN,
                configured=True,
            )
            for group in sorted(self.admin_groups)
        )
        return admins + self.rules

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
    roles: frozenset[str] = frozenset()
    """The values of the provider's role claim (Entra ID app roles, Keycloak client roles)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalGrant:
    """What a successful code exchange or refresh gives: the claims and a refresh token."""

    claims: ExternalClaims
    """Who signed in, and their groups."""
    refresh_token: str | None = field(default=None, repr=False)
    """Lets the memberships be checked again later; ``None`` when the provider issued none."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalIdentity:
    """An identity at a provider, linked to one account by (issuer, subject) and nothing else.

    An account has at most one identity per provider. The one it was created through is its
    *origin* (``linked_at`` is ``None``): an account without a password follows it, its role, its
    groups and its access (``access_until``). The others were linked by the account's owner from
    Account settings: they only sign the account in, and their times of access mean nothing.
    """

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
    linked_at: datetime | None = None
    """When the account's owner linked it from Account settings; ``None`` for the account's
    origin (the identity it was created through)."""

    @property
    def is_origin(self) -> bool:
        """Whether the account was created through this identity (and follows it).

        Returns:
            ``True`` unless it was linked from Account settings.
        """
        return self.linked_at is None

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
    link_session_hash: str | None = field(default=None, repr=False)
    """For a link from Account settings: the hash of the session that started it, which the
    callback must come back with (the identity is linked to its account, nobody is signed in);
    ``None`` for a sign-in."""

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


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessClaims:
    """Who Cloudflare Access says is calling, already checked by the verifier.

    A person has ``email`` and ``subject`` (Access's ``sub``, stable for the person within the
    team); a service token has ``common_name`` (its client ID) and an empty ``subject``.
    """

    issuer: str
    """The team domain that signed the token (its ``iss``)."""
    subject: str
    """The person's identifier at the team (``sub``); empty for a service token."""
    email: str | None = None
    """The person's email address; ``None`` for a service token."""
    common_name: str | None = None
    """The service token's client ID; ``None`` for a person."""


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessPolicy:
    """Who Cloudflare Access may sign in, and as which account.

    People are linked to an account by (team domain, Access ``sub``); a first visit creates the
    account only with ``auto_create_users``. ``admin_emails`` decides their role at every visit.
    A service token acts as the existing account its client ID is mapped to, and nothing else.
    """

    team_domain: str
    """``https://<team>.cloudflareaccess.com``: the tokens' issuer, without a trailing slash."""
    admin_emails: frozenset[str] = frozenset()
    """Emails (case-folded) whose accounts are ``admin``; everyone else Access creates is
    ``user``."""
    auto_create_users: bool = True
    """Create the account of a person's first visit; when off, only people linked already get in.
    """
    service_tokens: Mapping[str, Username] = field(default_factory=dict)
    """Service token client ID (``common_name``) to the username of the account it acts as."""

    def __post_init__(self) -> None:
        """Normalize the team domain and the admin emails.

        Raises:
            ValueError: The team domain is not an ``https://`` origin.
        """
        domain = self.team_domain.rstrip("/")
        parts = urlsplit(domain)
        if parts.scheme != "https" or not parts.hostname or parts.path:
            message = (
                "the Cloudflare Access team domain must be like https://<team>.cloudflareaccess.com"
            )
            raise ValueError(message)
        object.__setattr__(self, "team_domain", domain)
        object.__setattr__(
            self, "admin_emails", frozenset(email.strip().casefold() for email in self.admin_emails)
        )

    @property
    def provider(self) -> str:
        """The provider name Access accounts are linked under.

        Returns:
            ``cloudflare-access``.
        """
        return ACCESS_PROVIDER

    @property
    def sign_out_url(self) -> str:
        """Where the browser goes to sign out of Access (and so of ExactDocs).

        Returns:
            The team's logout URL.
        """
        return f"{self.team_domain}{ACCESS_LOGOUT_PATH}"

    def role_for(self, email: str) -> Role:
        """Return the role of the person with this email.

        Args:
            email: The person's email.

        Returns:
            ``admin`` when listed in ``admin_emails``, else ``user``.
        """
        return Role.ADMIN if email.strip().casefold() in self.admin_emails else Role.USER


def access_username_candidates(email: str) -> list[Username]:
    """Return the usernames a person's first Cloudflare Access visit may take, in order.

    The whole email, then its local part, then ``<local part>@cloudflare-access``; a name that is
    not a valid username or holds ``RESERVED_IN_USERNAME`` is skipped.

    Args:
        email: The person's email.

    Returns:
        The candidates, best first.
    """
    local = email.partition("@")[0]
    candidates: list[Username] = []
    for name in (email, local, f"{local}@{ACCESS_PROVIDER}"):
        try:
            username = Username(name)
        except InvalidUsernameError:
            continue
        if RESERVED_IN_USERNAME not in username.value and username not in candidates:
            candidates.append(username)
    return candidates


class LibraryRole(StrEnum):
    """What an account may do with one library (``viewer < contributor < admin < creator``).

    ``viewer`` searches and reads. ``contributor`` also imports content (versions, syncs, tags).
    ``admin`` also configures the library (paths, tag rules, chunking, retrieval, schedule) and
    removes versions. ``creator`` also removes the library and grants the ``admin`` role. An
    account's effective role on a library is the highest one it is granted, directly or through
    a group.
    """

    VIEWER = "viewer"
    CONTRIBUTOR = "contributor"
    ADMIN = "admin"
    CREATOR = "creator"

    @property
    def rank(self) -> int:
        """Order the roles: a higher rank may do everything a lower one may.

        Returns:
            0 for ``viewer`` up to 3 for ``creator``.
        """
        return list(LibraryRole).index(self)

    def allows(self, needed: LibraryRole) -> bool:
        """Tell whether this role may do what ``needed`` allows.

        Args:
            needed: The lowest role that may do it.

        Returns:
            ``True`` when this role is ``needed`` or higher.
        """
        return self.rank >= needed.rank


class SubjectKind(StrEnum):
    """Whom a library grant is for."""

    USER = "user"
    GROUP = "group"


@dataclass(frozen=True, slots=True, kw_only=True)
class LibraryGrant:
    """A role on one library, given to one account or to every member of one group."""

    library: str
    """The library ID (``/owner/repo``), lower-case."""
    kind: SubjectKind
    """Whether ``subject`` is an account ID or a group name."""
    subject: str
    """The account ID, or the group's name as ExactDocs stores it (``group_prefix`` included)."""
    role: LibraryRole
    """The role given."""


class AccessChange(StrEnum):
    """What changed about who may do what with a library (ACL-05)."""

    LIBRARY_CREATED = "library_created"
    """A person created the library and became its ``creator``."""
    GRANTED = "granted"
    """A user or a group got a role on the library, or another role than the one they had."""
    REVOKED = "revoked"
    """A user or a group lost their role on the library."""
    OWNERSHIP_TRANSFERRED = "ownership_transferred"
    """The ``creator`` role went to another account (the subject).

    The creators before, now admins, each get a ``granted`` event of their own.
    """
    LIBRARY_DELETED = "library_deleted"
    """The library was removed, and every grant on it with it."""


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessEvent:
    """One entry of the access log: who changed which library's access, how and when.

    A ``library_deleted`` event has no subject or role. Every other change names the user or
    group it is about and the role it holds afterwards (``revoked``: the role taken away). An
    ``ownership_transferred`` event names the new ``creator`` as its subject.
    """

    id: str
    """Unique, and sorts in the order the events were recorded (a UUIDv7)."""
    library: str
    """The library ID (``/owner/repo``), lower-case."""
    at: datetime
    """When it happened."""
    actor: AccountId | None
    """The account that made the change; ``None`` when the instance did (CLI, a job)."""
    change: AccessChange
    """What happened."""
    kind: SubjectKind | None = None
    """Whether ``subject`` is an account ID or a group name; ``None`` for a deletion."""
    subject: str | None = None
    """The account ID or group name the change is about; ``None`` for a deletion."""
    role: LibraryRole | None = None
    """The role given, or the role taken away; ``None`` for a deletion."""
    previous_role: LibraryRole | None = None
    """The role the subject held before a ``granted`` or ``ownership_transferred`` change."""

    def __post_init__(self) -> None:
        """Check that the event names a subject and a role exactly when it is about one.

        Raises:
            ValueError: A deletion names a subject or role, or another change lacks one.
        """
        about_someone = self.change is not AccessChange.LIBRARY_DELETED
        named = (self.kind, self.subject, self.role)
        if about_someone and None in named:
            message = f"a {self.change.value} event needs a subject and a role"
            raise ValueError(message)
        if not about_someone and (any(v is not None for v in named) or self.previous_role):
            message = "a library_deleted event names no subject or role"
            raise ValueError(message)

    def sort_value(self, field: str) -> str:
        """Return what the event sorts by in the log sorted by ``field``.

        Args:
            field: One of ``ACCESS_LOG_SORT_FIELDS``.

        Returns:
            ``at`` as fixed-width UTC ISO 8601 text with microseconds (as the log stores it, so
            the text sorts in time order), or the library ID, or the change.

        Raises:
            ValueError: The log cannot be sorted by ``field``.
        """
        match field:
            case "at":
                return self.at.astimezone(UTC).isoformat(timespec="microseconds")
            case "library":
                return self.library
            case "change":
                return self.change.value
        message = f"the access log cannot be sorted by {field!r}"
        raise ValueError(message)


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessLogFilter:
    """Which access events a page of the log is taken from."""

    library: str | None = None
    """Only this library's events (lower-case); ``None`` for every library."""
    changes: frozenset[AccessChange] | None = None
    """Only events of these changes; ``None`` for all."""
    newer_than: str | None = None
    """Only events recorded after the one with this ID."""
    actor: AccountId | None = None
    """Only events made by this account; ``None``: by anyone, the instance included."""
    subjects: frozenset[tuple[SubjectKind, str]] | None = None
    """Only events about one of these users (account IDs) or groups (names as stored);
    ``None``: about anyone, deletions included."""
    at_after: datetime | None = None
    """Only events that happened at or after this time."""
    at_before: datetime | None = None
    """Only events that happened before this time."""


def effective_role(grants: Iterable[LibraryGrant]) -> LibraryRole | None:
    """Return the highest role of the grants.

    Args:
        grants: The grants that apply to one account on one library.

    Returns:
        The highest role, or ``None`` without a grant.
    """
    return max((grant.role for grant in grants), key=lambda role: role.rank, default=None)


@dataclass(frozen=True, slots=True, kw_only=True)
class LibraryCreationPolicy:
    """An operator's instance-wide creation allowlist; empty permits operators only."""

    users: frozenset[str] = frozenset()
    """Exact stable account IDs, including verified unlinked provider:subject IDs."""
    groups: frozenset[str] = frozenset()
    """Exact mapped group names, including any provider prefix."""

    @property
    def role_rules(self) -> tuple[RoleRule, ...]:
        """``groups`` as read-only rules of any provider.

        Returns:
            One ``create_libraries`` rule per group.
        """
        return tuple(
            RoleRule(
                id=f"config:library_creation:{group}",
                provider=None,
                source=RuleSource.GROUP,
                value=group,
                grant=RuleGrant.CREATE_LIBRARIES,
                configured=True,
            )
            for group in sorted(self.groups)
        )


class RuleSource(StrEnum):
    """What a role rule matches: a GitHub organization or team, a group, or a role value."""

    GITHUB_ORG = "github_org"
    """Active members of a GitHub organization (group ``github:<org>``)."""
    GITHUB_TEAM = "github_team"
    """Active members of a GitHub team, ``org/team-slug`` (group ``github:<org>/<team>``)."""
    GROUP = "group"
    """Members of a group of the provider's groups claim, as the provider names it."""
    ROLE = "role"
    """Holders of a value of the provider's role claim."""


class RuleGrant(StrEnum):
    """What a role rule gives: an instance role, or a role on libraries."""

    INSTANCE_ADMIN = "instance_admin"
    """The account role ``admin``: an operator."""
    CREATE_LIBRARIES = "create_libraries"
    """May create libraries where ``[library_creation]`` restricts it."""
    VIEWER = "viewer"
    CONTRIBUTOR = "contributor"
    ADMIN = "admin"

    @property
    def library_role(self) -> LibraryRole | None:
        """The library role this grant gives.

        Returns:
            The role, or ``None`` for an instance grant.
        """
        if self in {RuleGrant.INSTANCE_ADMIN, RuleGrant.CREATE_LIBRARIES}:
            return None
        return LibraryRole(self.value)


@dataclass(frozen=True, slots=True, kw_only=True)
class Memberships:
    """What role rules can match about one account: its origin provider, groups and roles."""

    provider: str | None
    """The provider the account was created through; ``None`` for a local account."""
    groups: frozenset[str] = frozenset()
    """Its groups, as ExactDocs stores them (``group_prefix`` included)."""
    roles: frozenset[str] = frozenset()
    """Its role claim values, as the provider sends them."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RoleRule:
    """Who gets what from their memberships at a sign-in provider (#577).

    A rule pairs a source (a GitHub organization or team, a group, a role value) with a grant
    (instance admin, may create libraries, or a library role on every library or on some). It
    only ever adds: an account's access is the highest of its own and its rules'. "Every
    library" leaves out private libraries, which a rule reaches only by naming them.
    """

    id: str
    """Unique; ``config:...`` for a rule of the configuration file."""
    provider: str | None
    """The sign-in provider whose accounts it matches; ``None`` for any (only
    ``[library_creation].groups``, whose names carry their prefix already)."""
    source: RuleSource
    """What kind of membership it matches."""
    value: str
    """The organization, ``org/team``, group or role value, as the provider names it."""
    grant: RuleGrant
    """What it gives."""
    libraries: frozenset[str] | None = None
    """The libraries a library role is given on (lower-case IDs); ``None`` for every library
    that is not private. Always ``None`` for an instance grant."""
    configured: bool = False
    """Set by the configuration file, so read-only."""
    created_by: AccountId | None = None
    """Who added a stored rule."""
    created_at: datetime | None = None
    """When a stored rule was added."""

    def __post_init__(self) -> None:
        """Check the value's form and that only a library role names libraries.

        Raises:
            InvalidRoleRuleError: The value is blank or not a GitHub name where one is needed,
                libraries are named for an instance grant or are not library IDs, or a rule of
                any provider is not a group rule.
        """
        if problem := self._problem():
            raise InvalidRoleRuleError(problem)

    def _problem(self) -> str | None:
        """Say what makes the rule unusable.

        Returns:
            The reason, or ``None`` for a usable rule.
        """
        patterns = {
            RuleSource.GITHUB_ORG: (
                GITHUB_ORG_PATTERN,
                "a GitHub organization is a name like acme",
            ),
            RuleSource.GITHUB_TEAM: (GITHUB_TEAM_PATTERN, "a GitHub team is org/team-slug"),
        }
        # The configuration file's group names (admin_groups) are taken as they are written.
        if not self.configured and (not self.value or self.value != self.value.strip()):
            return "the source must not be blank or padded"
        if self.provider is None and not (
            self.configured
            and self.source is RuleSource.GROUP
            and self.grant is RuleGrant.CREATE_LIBRARIES
        ):
            return "only [auth.library_creation].groups apply to every provider"
        if self.source in patterns and not re.fullmatch(patterns[self.source][0], self.value):
            return patterns[self.source][1]
        if self.libraries is not None and self.grant.library_role is None:
            return "only a library role is given on chosen libraries"
        if self.libraries is not None and (
            not self.libraries
            or any(
                library != library.casefold() or not re.fullmatch(LIBRARY_ID_PATTERN, library)
                for library in self.libraries
            )
        ):
            return "libraries must be lower-case /owner/repo IDs"
        return None

    def matches(self, memberships: Memberships, policies: Mapping[str, SignInPolicy]) -> bool:
        """Tell whether the rule applies to an account with these memberships.

        A rule applies only to accounts of its provider, while that provider is configured; a
        stored rule not at all while the provider takes only configured rules. GitHub names
        compare without case, as GitHub's do.

        Args:
            memberships: The account's provider, groups and roles.
            policies: The configured providers, by name (for ``group_prefix``).

        Returns:
            Whether it applies.
        """
        if self.provider is None:
            return self.value in memberships.groups
        policy = policies.get(self.provider)
        if (
            policy is None
            or memberships.provider != self.provider
            or (policy.configured_rules_only and not self.configured)
        ):
            return False
        if self.source is RuleSource.ROLE:
            return self.value in memberships.roles
        if self.source is RuleSource.GROUP:
            return f"{policy.group_prefix}{self.value}" in memberships.groups
        name = f"{policy.group_prefix}github:{self.value}".casefold()
        return policy.github and any(group.casefold() == name for group in memberships.groups)


def github_rule_targets(
    rules: Iterable[RoleRule], provider: str
) -> tuple[frozenset[str], frozenset[str]]:
    """Return the GitHub organizations and teams the rules of a provider name.

    Args:
        rules: The rules in force.
        provider: The GitHub provider's name.

    Returns:
        The organizations and the ``org/team`` names, case folded.
    """
    mine = [rule for rule in rules if rule.provider == provider]
    return (
        frozenset(r.value.casefold() for r in mine if r.source is RuleSource.GITHUB_ORG),
        frozenset(r.value.casefold() for r in mine if r.source is RuleSource.GITHUB_TEAM),
    )


def instance_role_by_rules(
    rules: Iterable[RoleRule], memberships: Memberships, policies: Mapping[str, SignInPolicy]
) -> Role:
    """Return the account role the rules give these memberships.

    Args:
        rules: The rules in force.
        memberships: The account's provider, groups and roles.
        policies: The configured providers, by name.

    Returns:
        ``admin`` while an ``instance_admin`` rule matches, else ``user``.
    """
    admin = any(
        rule.grant is RuleGrant.INSTANCE_ADMIN and rule.matches(memberships, policies)
        for rule in rules
    )
    return Role.ADMIN if admin else Role.USER


class Theme(StrEnum):
    """The colour scheme of the interface; ``system`` follows the operating system's."""

    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


class Contrast(StrEnum):
    """How strongly text and controls stand out from their background."""

    STANDARD = "standard"
    MORE = "more"


class TextSpacing(StrEnum):
    """The spacing of lines, words and letters (``wide`` meets WCAG 1.4.12's minimums)."""

    STANDARD = "standard"
    WIDE = "wide"


class Motion(StrEnum):
    """Animations: ``system`` follows the operating system's reduced-motion setting."""

    SYSTEM = "system"
    REDUCED = "reduced"
    FULL = "full"


class Font(StrEnum):
    """The typeface of the interface's text."""

    DEFAULT = "default"
    HYPERLEGIBLE = "hyperlegible"
    DYSLEXIC = "dyslexic"
    SYSTEM = "system"


class Language(StrEnum):
    """The language of the interface; ``system`` follows the browser's."""

    SYSTEM = "system"
    EN = "en"
    PL = "pl"


# The text sizes the interface offers, in percent: ``TEXT_SCALES`` as a type.
TextScale = Literal[90, 100, 110, 125, 150]


@dataclass(frozen=True, slots=True, kw_only=True)
class Preferences:
    """How one person wants the interface to look and behave, saved to their account (#487).

    The defaults are what an account that never saved any gets: follow the operating system and
    change nothing else.
    """

    theme: Theme = Theme.SYSTEM
    """The colour scheme."""
    contrast: Contrast = Contrast.STANDARD
    """The contrast level."""
    text_scale: TextScale = 100
    """The text size in percent, one of ``TEXT_SCALES``."""
    text_spacing: TextSpacing = TextSpacing.STANDARD
    """The spacing of lines, words and letters."""
    motion: Motion = Motion.SYSTEM
    """Whether the interface animates."""
    font: Font = Font.DEFAULT
    """The typeface."""
    underline_links: bool = False
    """Whether every link is underlined, not only told apart by its colour."""
    large_targets: bool = False
    """Whether buttons and links get larger hit areas."""
    language: Language = Language.SYSTEM
    """The language of the interface."""
    library_logos: bool = True
    """Whether libraries show their logos (and generic icons where they have none)."""
    leaderboard_opt_in: bool = False
    """Whether the person agreed to be shown by name on the people leaderboard (#510), while the
    operator has it on; nobody is shown without agreeing."""

    def __post_init__(self) -> None:
        """Check the text size.

        Raises:
            InvalidPreferencesError: The text size is not one of ``TEXT_SCALES``.
        """
        if self.text_scale not in TEXT_SCALES:
            sizes = ", ".join(str(scale) for scale in TEXT_SCALES)
            message = f"text_scale must be one of {sizes} (percent)"
            raise InvalidPreferencesError(message)
