"""Data crossing the identity boundary (into and out of driving ports). Immutable, validated."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_serializer,
    field_validator,
    model_validator,
)

from exactdocs.identity.constants import (
    ALL_TOKENS_SORT_FIELDS,
    GRANT_SORT_FIELDS,
    LOCAL_SIGN_IN,
    MAX_PASSWORD_LENGTH,
    MAX_RETURN_TO_LENGTH,
    MAX_TOKEN_NAME_INPUT,
    MAX_USERNAME_LENGTH,
    MIN_PASSWORD_LENGTH,
    NEW_PASSWORD_DESCRIPTION,
    NEW_USERNAME_DESCRIPTION,
    TOKEN_NAME_DESCRIPTION,
    TOKEN_SORT_FIELDS,
    USER_SORT_FIELDS,
    USERNAME_DESCRIPTION,
)
from exactdocs.identity.models import (
    AccessEvent,
    Account,
    ApiToken,
    LibraryGrant,
    LibraryRole,
    SignInPolicy,
    activity_hour,
)
from exactdocs_kernel import (
    DEFAULT_LIMIT,
    LIBRARY_ID_PATTERN,
    MAX_LIMIT,
    MAX_NAME,
    MAX_OFFSET,
    Page,
)


class _Dto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class _PageQuery(_Dto):
    """One page of a list: ``limit`` items after the opaque ``cursor`` of the previous page."""

    limit: Annotated[int, Field(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT
    """How many items per page."""
    cursor: str | None = None
    """Opaque: only ever a `next_cursor`; absent for the first page. It only works with the
    `sort` and filters of the request that returned it."""
    offset: Annotated[int, Field(ge=0, le=MAX_OFFSET)] | None = None
    """Jump to a page: skip this many matches, in the order and with the filters of the cursor
    walk. Not with `cursor`; the page's `next_cursor` goes on from it."""
    q: str | None = Field(default=None, max_length=MAX_NAME)
    """Only items whose name contains this text, any case: a user's username, a token's name, a
    grant's username or group."""


_LibraryId = Annotated[str, Field(pattern=LIBRARY_ID_PATTERN, max_length=MAX_NAME)]
_SortedLibraryIds = Annotated[list[_LibraryId], Field(json_schema_extra={"uniqueItems": True})]


class _LibrarySelection(_Dto):
    """An optional, canonical selection of libraries; an empty selection allows none."""

    library_ids: frozenset[_LibraryId] | None = None
    """Selected library IDs; omit or use null for all libraries the user can access."""

    @field_validator("library_ids")
    @classmethod
    def _canonical_libraries(cls, value: frozenset[str] | None) -> frozenset[str] | None:
        """Normalize the library selection.

        Args:
            value: The optional selected IDs.

        Returns:
            Casefolded unique IDs, preserving unrestricted and empty selections.
        """
        return None if value is None else frozenset(library.casefold() for library in value)

    @field_serializer("library_ids")
    def _sorted_libraries(self, value: frozenset[str] | None) -> _SortedLibraryIds | None:
        """Serialize the selection in a stable order (a set's order varies per process).

        Args:
            value: The canonical selected IDs.

        Returns:
            The IDs sorted, or ``None`` for an unrestricted selection.
        """
        return None if value is None else sorted(value)


class AccountSummary(_Dto):
    """An account as the outside world sees it (never the password hash)."""

    id: str
    """Stable identifier of the account."""
    username: str
    """The login name, normalised (NFKC, trimmed, case-folded): `Admin` signs in as `admin`."""
    role: str
    """What the account may do: `admin` (an operator, who also manages accounts) or `user`."""
    has_password: bool = False
    """Whether the account has a local password: it signs in with it and may change it
    (`PUT /api/v1/account/password`). `false` for an account that only signs in through an
    identity provider (or Cloudflare Access), which has no password to change."""

    @classmethod
    def from_model(cls, account: Account) -> Self:
        """Map a domain entity to its boundary representation.

        Args:
            account: The account.

        Returns:
            Its summary.
        """
        return cls(
            id=account.id,
            username=account.username.value,
            role=account.role.value,
            has_password=not account.is_external,
        )


class ApiTokenIdentity(AccountSummary, _LibrarySelection):
    """A verified API credential and the account it acts as; never parsed from token claims."""

    token_id: str
    """Stable credential ID, without its secret."""


class ExternalTokenIdentity(_Dto):
    """The verified identity of one OAuth request, without changing web-account state."""

    account: AccountSummary
    """The linked account, or the synthetic provider/subject caller."""
    groups: frozenset[str]
    """Groups from this signed ID token, mapped with the provider's group prefix."""
    linked: bool
    """Whether this caller must still have its linked account in the repository."""


class SetupState(_Dto):
    """Whether the instance still waits for its first admin."""

    setup_required: bool
    """`true` while no account exists: the first admin must be created before anyone signs in."""


class CreateFirstAdminCommand(_Dto):
    """The first admin's credentials. The password is a ``SecretStr``: never shown in a repr."""

    username: str = Field(description=USERNAME_DESCRIPTION)
    """Login name of the first admin; its schema description is ``USERNAME_DESCRIPTION``."""
    password: SecretStr = Field(
        min_length=MIN_PASSWORD_LENGTH,
        max_length=MAX_PASSWORD_LENGTH,
        description=f"Password of the first admin, {NEW_PASSWORD_DESCRIPTION}",
    )
    """Password of the first admin; its schema description names the length limits."""


class AuthenticateQuery(_Dto):
    """A username and password to check."""

    username: str = Field(max_length=4 * MAX_USERNAME_LENGTH)  # cap the input before normalising
    """Login name of the account, compared case-insensitively."""
    password: SecretStr = Field(max_length=MAX_PASSWORD_LENGTH)
    """Password of the account."""


class LoginForTokenCommand(_LibrarySelection):
    """Credentials exchanged for an API token (the CLI's login); ``name`` labels the token."""

    username: str = Field(max_length=4 * MAX_USERNAME_LENGTH)
    """Login name of the account, compared case-insensitively."""
    password: SecretStr = Field(max_length=MAX_PASSWORD_LENGTH)
    """Password of the account."""
    name: str = Field(max_length=MAX_TOKEN_NAME_INPUT, description=TOKEN_NAME_DESCRIPTION)
    """Label of the new token; its schema description is ``TOKEN_NAME_DESCRIPTION``."""
    expires_at: AwareDatetime | None = None
    """When the token stops working (in the future, with a timezone); omit it for no expiry."""


class _OneAccount(_Dto):
    """Names one existing account, by exactly one of its id and its username."""

    id: str | None = None
    """The account's id (the users page names accounts this way)."""
    username: str | None = None
    """Login name of the account, compared case-insensitively (the command line's way)."""

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        """Check that exactly one of ``id`` and ``username`` is given.

        Returns:
            The command, unchanged.

        Raises:
            ValueError: Neither or both are given.
        """
        if (self.id is None) == (self.username is None):
            message = "give exactly one of id and username"
            raise ValueError(message)
        return self


class ResetPasswordCommand(_OneAccount):
    """A new password for an existing account (the operator's recovery path)."""

    password: SecretStr = Field(
        min_length=MIN_PASSWORD_LENGTH,
        max_length=MAX_PASSWORD_LENGTH,
        description=f"The new password, {NEW_PASSWORD_DESCRIPTION}",
    )
    """The new password; its schema description names the length limits."""


class NewPassword(_Dto):
    """A new password an operator sets for an account on the users page."""

    password: SecretStr = Field(
        min_length=MIN_PASSWORD_LENGTH,
        max_length=MAX_PASSWORD_LENGTH,
        description=f"The new password, {NEW_PASSWORD_DESCRIPTION}",
    )
    """The new password; its schema description names the length limits."""


class ChangePasswordCommand(_Dto):
    """A signed-in person's own password change: the current password, then the new one."""

    current_password: SecretStr = Field(max_length=MAX_PASSWORD_LENGTH)
    """The account's password now; a wrong one is refused with `wrong_password` (403) and
    counts against the sign-in throttle like a failed sign-in."""
    new_password: SecretStr = Field(
        min_length=MIN_PASSWORD_LENGTH,
        max_length=MAX_PASSWORD_LENGTH,
        description=f"The new password, {NEW_PASSWORD_DESCRIPTION}",
    )
    """The new password; its schema description names the length limits (those of the setup)."""


class SetUserDisabledCommand(_OneAccount):
    """Disable an account (it is locked out at once) or enable it again."""

    disabled: bool
    """`true` to disable the account, `false` to let it sign in again."""


class CreateUserCommand(_Dto):
    """A new local account, created by an operator. There is no self-signup."""

    username: str = Field(max_length=4 * MAX_USERNAME_LENGTH, description=NEW_USERNAME_DESCRIPTION)
    """Login name of the new account; its schema description is ``NEW_USERNAME_DESCRIPTION``."""
    password: SecretStr = Field(
        min_length=MIN_PASSWORD_LENGTH,
        max_length=MAX_PASSWORD_LENGTH,
        description=f"Password of the new account, {NEW_PASSWORD_DESCRIPTION}",
    )
    """Password of the new account; its schema description names the length limits."""
    role: Literal["admin", "user"] = "user"
    """`user` (the default) signs in and uses the instance; `admin` also manages accounts."""


class UserSummary(AccountSummary):
    """An account as an operator sees it on the users page."""

    created_at: datetime
    """When the account was created."""
    disabled: bool
    """`true` while the account is disabled: it cannot sign in, and its sessions and tokens are
    refused."""
    provider: str | None = None
    """The sign-in provider the account signs in through; `null` for a local account (password).
    An account created through a provider keeps that provider here."""
    groups: list[str] = Field(default_factory=list)
    """The account's groups at its identity provider, as of its latest sign-in or revalidation
    (with the provider's `group_prefix`); empty for a local account."""
    last_active_at: datetime | None = None
    """The hour (UTC, minutes always zero) of the account's latest sign-in or request with one
    of its sessions or API tokens; `null` while it has not been active since this was recorded."""
    token_count: int = 0
    """How many API tokens the account holds that have not expired."""

    @classmethod
    def from_model(
        cls,
        account: Account,
        *,
        provider: str | None = None,
        groups: list[str] | None = None,
        token_count: int = 0,
    ) -> Self:
        """Map a domain entity to its boundary representation.

        Args:
            account: The account.
            provider: The provider of an external account.
            groups: The groups of an external account.
            token_count: How many live API tokens the account holds.

        Returns:
            Its summary, with when it was created, whether it is disabled, where it signs in,
            when it was last active (to the hour) and how many tokens it holds.
        """
        active = account.last_active_at
        return cls(
            id=account.id,
            username=account.username.value,
            role=account.role.value,
            has_password=not account.is_external,
            created_at=account.created_at,
            disabled=account.is_disabled,
            provider=provider,
            groups=groups or [],
            last_active_at=None if active is None else activity_hour(active),
            token_count=token_count,
        )


class UserListQuery(_PageQuery):
    """How the users list is filtered, sorted and paged."""

    sort: str | None = Field(
        default=None,
        max_length=MAX_NAME,
        description=(
            f"Sort by one of {', '.join(USER_SORT_FIELDS)}; prefix `-` for descending. "
            "Default: `created_at`. An unknown field is a 422."
        ),
    )
    """The sort field; its schema description names ``USER_SORT_FIELDS``."""
    role: list[Literal["admin", "user"]] | None = Field(
        default=None, description="Only accounts with one of these roles; repeat for several."
    )
    """Only accounts with one of these roles."""
    disabled: bool | None = None
    """`true`: only disabled accounts; `false`: only enabled ones."""
    provider: list[Annotated[str, Field(max_length=MAX_NAME)]] | None = Field(
        default=None,
        description=(
            f"Only accounts that sign in through one of these: `{LOCAL_SIGN_IN}` for a local "
            "account, else the provider's name, as `provider` shows it (the provider the account "
            "was created through); repeat for several."
        ),
    )
    """Only accounts with one of these sign-in providers (``LOCAL_SIGN_IN`` for a local one)."""


class UserList(_Dto):
    """A page of the accounts, oldest first unless sorted otherwise."""

    users: list[UserSummary]
    """The accounts of this page."""
    next_cursor: str | None
    """Pass as `cursor` to get the next page; null on the last page."""
    total: int
    """How many accounts match the filters, across every page."""

    @classmethod
    def from_page(cls, page: Page[UserSummary]) -> Self:
        """Wrap a page of accounts.

        Args:
            page: The accounts and the cursor of the next page.

        Returns:
            The page at the boundary.
        """
        return cls(users=list(page.items), next_cursor=page.next_cursor, total=page.total or 0)


ThrottleReset = Literal["cleared", "busy", "failed"]
"""What became of a username's sign-in throttle count and remembered sign-ins when its password
was reset."""


class PasswordReset(_Dto):
    """The outcome of a password reset: the password, sessions and tokens are always done."""

    account: AccountSummary
    """The account whose password changed, with its stored (normalised) username."""
    throttle: ThrottleReset
    """What became of the username's sign-in throttle count and of the addresses the throttle
    remembers for it: ``cleared`` (both are gone, or there were none), ``busy`` (the throttle
    could not take its turn in time, so the count stays until it is waited out, or the addresses
    go on skipping the username's count until they are forgotten) or ``failed`` (another error;
    either may stay). The worse of the two is reported. Running the reset again is safe in
    either case."""


class SessionGrant(_Dto):
    """A new session. ``token`` is the only copy of the secret; hand it to the browser."""

    token: SecretStr
    """The session's secret, handed to the browser as the session cookie (never sent as JSON)."""
    account: AccountSummary
    """The account now signed in."""
    max_age: int
    """Seconds until the session cannot be used any more, even if never idle."""


class SignInProviderSummary(_Dto):
    """A configured identity provider, as the sign-in page offers it."""

    name: str
    """The provider's name: sign in at `GET /api/v1/auth/{name}/start`."""
    display_name: str
    """What its sign-in button says."""

    @classmethod
    def from_model(cls, policy: SignInPolicy) -> Self:
        """Map a provider's policy to what the sign-in page shows.

        Args:
            policy: The provider's policy.

        Returns:
            Its name and display name.
        """
        return cls(name=policy.name, display_name=policy.display_name)


class SessionState(_Dto):
    """What the UI needs to know first: is setup due, is anyone signed in, and who."""

    state: Literal["setup_required", "signed_out", "signed_in"]
    """`setup_required` while no account exists, else whether the caller is signed in."""
    account: AccountSummary | None = None
    """The signed-in account; `null` unless `state` is `signed_in`."""
    providers: list[SignInProviderSummary] = Field(default_factory=list)
    """The identity providers one may sign in with besides a password; empty when none is
    configured (and while setup is due: the first admin is always local)."""
    source: Literal["session", "cloudflare_access"] | None = None
    """How the caller is signed in: an ExactDocs session cookie, or the Cloudflare Access token
    of the request; `null` unless `state` is `signed_in`."""
    sign_out_url: str | None = None
    """Where to send the browser to sign out when `source` is `cloudflare_access` (Access's own
    logout: ending the ExactDocs session alone would sign it in again); `null` otherwise."""


class StartExternalSignInCommand(_Dto):
    """Start signing in through an identity provider."""

    provider: str
    """The provider's name."""
    return_to: str | None = Field(default=None, max_length=4 * MAX_RETURN_TO_LENGTH)
    """Where to go once signed in: a path on this server; anything else means `/`."""


class ExternalSignInStart(_Dto):
    """A started external sign-in: send the browser to ``redirect_url`` with the binding cookie."""

    redirect_url: str
    """The identity provider's authorization URL."""
    binding: SecretStr
    """The secret that binds the attempt to this browser, handed to it as a cookie."""
    max_age: int
    """Seconds the attempt may take."""


class FinishExternalSignInCommand(_Dto):
    """The identity provider's callback, with the browser's binding cookie."""

    provider: str
    """The provider's name, from the callback's path."""
    binding: SecretStr | None = None
    """The browser's binding cookie, if it sent one."""
    state: str | None = Field(default=None, max_length=512)
    """`state`, as the provider sent it back."""
    code: str | None = Field(default=None, max_length=4096)
    """The authorization code."""
    error: str | None = Field(default=None, max_length=256)
    """The provider's error, when it did not sign the person in."""


class ExternalSignInResult(_Dto):
    """A finished external sign-in: the new session, and where the browser goes now."""

    session: SessionGrant
    """The new session."""
    return_to: str
    """The same-origin path the sign-in was started for."""


class RevalidationReport(_Dto):
    """What one revalidation pass did with the external identities that were due."""

    extended: int = 0
    """Still allowed: access moved forward, groups and role refreshed."""
    revoked: int = 0
    """Membership lost or token refused: access ended, sessions deleted."""
    unreachable: int = 0
    """The provider could not be reached: access left as it was (it ends after the grace)."""
    superseded: int = 0
    """The link changed while the provider answered (a disable, a revocation or a sign-in):
    the answer was dropped and the newer state kept."""


class CreateTokenCommand(_LibrarySelection):
    """A new API token for the caller. ``expires_at`` (timezone-aware) is optional."""

    name: str = Field(max_length=MAX_TOKEN_NAME_INPUT, description=TOKEN_NAME_DESCRIPTION)
    """Label of the new token; its schema description is ``TOKEN_NAME_DESCRIPTION``."""
    expires_at: AwareDatetime | None = None
    """When the token stops working (in the future, with a timezone); omit it for no expiry."""


class TokenSummary(_LibrarySelection):
    """A token as listed: everything but the secret."""

    id: str
    """Stable identifier of the token, used to revoke it."""
    name: str
    """Label the token was given when it was created."""
    prefix: str
    """The first characters of the secret (`exd_` and four more), to recognise the token."""
    created_at: datetime
    """When the token was created."""
    expires_at: datetime | None
    """When the token stops working; `null` for a token that never expires."""
    last_used_at: datetime | None
    """When the token last authenticated a request; `null` if it was never used."""

    @classmethod
    def from_model(cls, token: ApiToken) -> Self:
        """Map a domain entity to its boundary representation.

        Args:
            token: The token.

        Returns:
            Its summary, without the secret.
        """
        return cls(
            id=token.id,
            name=token.name,
            prefix=token.prefix,
            created_at=token.created_at,
            expires_at=token.expires_at,
            last_used_at=token.last_used_at,
            library_ids=token.library_ids,
        )


class TokenListQuery(_PageQuery):
    """How the caller's token list is filtered, sorted and paged."""

    sort: str | None = Field(
        default=None,
        max_length=MAX_NAME,
        description=(
            f"Sort by one of {', '.join(TOKEN_SORT_FIELDS)}; prefix `-` for descending. "
            "Default: `-created_at`. A token that never expires or was never used sorts first "
            "by `expires_at` or `last_used_at`. An unknown field is a 422."
        ),
    )
    """The sort field; its schema description names ``TOKEN_SORT_FIELDS``."""


class TokenList(_Dto):
    """A page of the caller's tokens, newest first unless sorted otherwise."""

    tokens: list[TokenSummary]
    """The tokens of this page."""
    next_cursor: str | None
    """Pass as `cursor` to get the next page; null on the last page."""
    total: int
    """How many of the caller's tokens match the filters, across every page."""

    @classmethod
    def from_page(cls, page: Page[TokenSummary]) -> Self:
        """Wrap a page of tokens.

        Args:
            page: The tokens and the cursor of the next page.

        Returns:
            The page at the boundary.
        """
        return cls(tokens=list(page.items), next_cursor=page.next_cursor, total=page.total or 0)


class AccountTokenSummary(TokenSummary):
    """A token as an operator sees it in the list of every token: with its owner, no secret."""

    owner_id: str
    """The id of the account that holds the token."""
    owner: str
    """The username of the account that holds the token."""

    @classmethod
    def of(cls, token: ApiToken, owner: str) -> Self:
        """Map a token and its owner's username to their boundary representation.

        Args:
            token: The token.
            owner: The username of its account.

        Returns:
            Its summary, with its owner, without the secret.
        """
        return cls(
            **TokenSummary.from_model(token).model_dump(), owner_id=token.account_id, owner=owner
        )


class AllTokensQuery(_PageQuery):
    """How the list of every account's tokens is filtered, sorted and paged."""

    sort: str | None = Field(
        default=None,
        max_length=MAX_NAME,
        description=(
            f"Sort by one of {', '.join(ALL_TOKENS_SORT_FIELDS)}; prefix `-` for descending. "
            "Default: `-created_at`. A token that never expires or was never used sorts first "
            "by `expires_at` or `last_used_at`; `owner` sorts by username. An unknown field is "
            "a 422."
        ),
    )
    """The sort field; its schema description names ``ALL_TOKENS_SORT_FIELDS``."""
    owner_id: str | None = Field(default=None, max_length=MAX_NAME)
    """Only the tokens of the account with this id."""
    expired: bool | None = None
    """`true`: only tokens whose expiry has passed (they no longer work); `false`: only the
    others."""
    unused: bool | None = None
    """`true`: only tokens that never authenticated a request; `false`: only used ones."""


class AllTokensList(_Dto):
    """A page of every account's tokens, newest first unless sorted otherwise."""

    tokens: list[AccountTokenSummary]
    """The tokens of this page."""
    next_cursor: str | None
    """Pass as `cursor` to get the next page; null on the last page."""
    total: int
    """How many tokens match the filters, across every page."""

    @classmethod
    def from_page(cls, page: Page[AccountTokenSummary]) -> Self:
        """Wrap a page of tokens.

        Args:
            page: The tokens and the cursor of the next page.

        Returns:
            The page at the boundary.
        """
        return cls(tokens=list(page.items), next_cursor=page.next_cursor, total=page.total or 0)


class TokenGrant(TokenSummary):
    """A new token. ``token`` is the only copy of the secret and is never shown again."""

    token: str = Field(repr=False)
    """The token's secret, shown only this once: send it as `Authorization: Bearer <token>`."""


class LibraryRolesQuery(_Dto):
    """Ask what one authenticated caller may do with libraries."""

    account_id: str
    """The account."""
    libraries: list[str]
    """Library IDs (``/owner/repo``)."""
    external_identity: ExternalTokenIdentity | None = None
    """Trusted request identity from the token verifier; never accepted from client arguments."""


class LibraryRoles(_Dto):
    """An account's effective role on each library asked about."""

    roles: dict[str, str]
    """Library ID (lower-case) to the role: `viewer`, `contributor`, `admin` or `creator`. A
    library the account has no role on is left out."""

    def allows(self, library: str, needed: str) -> bool:
        """Tell whether the account's role on a library is ``needed`` or higher.

        Args:
            library: The library ID, any case.
            needed: The lowest role that may do it: `viewer`, `contributor`, `admin` or
                `creator`.

        Returns:
            ``False`` when the account has no role on the library.
        """
        role = self.roles.get(library.casefold())
        return role is not None and LibraryRole(role).allows(LibraryRole(needed))


class ClaimLibraryCommand(_Dto):
    """Make an account the creator of a new library, dropping every earlier grant on its ID."""

    account_id: str
    """The account that created the library."""
    library: str
    """The library ID."""


class DropLibraryGrantsCommand(_Dto):
    """Drop every grant on a library that no longer exists."""

    library: str
    """The library ID."""
    actor_id: str | None = None
    """The account that removed the library; ``None`` when the instance did (CLI, a job)."""


class LibraryGrantRequest(_Dto):
    """Give a user or a group a role on a library (replacing the role they had)."""

    kind: Literal["user", "group"]
    """Whether `subject` is a username or a group name."""
    subject: str = Field(min_length=1, max_length=256)
    """The username, or the group's name as ExactDocs stores it (with the provider's prefix)."""
    role: Literal["viewer", "contributor", "admin"]
    """The role to give. `creator` is not given: the library's creator holds it."""


class GrantLibraryRoleCommand(LibraryGrantRequest):
    """A grant, made by a caller."""

    caller_id: str
    """The account that shares the library."""
    library: str
    """The library ID."""


class RevokeLibraryRoleCommand(_Dto):
    """Take a role away from a user or a group, made by a caller."""

    caller_id: str
    """The account that stops sharing."""
    library: str
    """The library ID."""
    kind: Literal["user", "group"]
    """Whether `subject` is a username or a group name."""
    subject: str
    """The username or the group's name."""


class LibraryTransferRequest(_Dto):
    """Hand a library over to another user: they become its creator."""

    username: str = Field(min_length=1, max_length=256)
    """The username of the new creator. The creator before becomes an `admin` of the library."""


class TransferLibraryCommand(LibraryTransferRequest):
    """A transfer of a library's ownership, made by a caller."""

    caller_id: str
    """The account that hands the library over."""
    library: str
    """The library ID."""


class GrantListQuery(_PageQuery):
    """How a library's grants are filtered, sorted and paged."""

    sort: str | None = Field(
        default=None,
        max_length=MAX_NAME,
        description=(
            f"Sort by one of {', '.join(GRANT_SORT_FIELDS)}; prefix `-` for descending. "
            "Default: `kind` (users, then groups, by name). `role` sorts from `viewer` up to "
            "`creator`. An unknown field is a 422."
        ),
    )
    """The sort field; its schema description names ``GRANT_SORT_FIELDS``."""
    kind: list[Literal["user", "group"]] | None = Field(
        default=None, description="Only grants to users or to groups; repeat for both."
    )
    """Only grants of these kinds."""
    role: list[Literal["viewer", "contributor", "admin", "creator"]] | None = Field(
        default=None, description="Only grants of one of these roles; repeat for several."
    )
    """Only grants of these roles."""


class ListLibraryGrantsQuery(GrantListQuery):
    """List who may do what with a library, asked by a caller."""

    caller_id: str
    """The account that asks."""
    library: str
    """The library ID."""


class LibraryGrantSummary(_Dto):
    """One grant as the outside world sees it."""

    kind: Literal["user", "group"]
    """Whether `subject` is a username or a group name."""
    subject: str
    """The username, or the group's name."""
    role: str
    """The role: `viewer`, `contributor`, `admin` or `creator`."""

    @classmethod
    def from_model(cls, grant: LibraryGrant, *, subject: str) -> Self:
        """Map a grant to its boundary representation.

        Args:
            grant: The grant.
            subject: What to show as its subject (a user's name, not its ID).

        Returns:
            Its summary.
        """
        return cls(kind=grant.kind.value, subject=subject, role=grant.role.value)


class LibraryGrants(_Dto):
    """Everyone who holds a role on a library."""

    grants: list[LibraryGrantSummary]
    """The grants: users first, then groups, by name."""


class LibraryGrantList(_Dto):
    """A page of a library's grants: users first, then groups, by name unless sorted otherwise."""

    grants: list[LibraryGrantSummary]
    """The grants of this page."""
    next_cursor: str | None
    """Pass as `cursor` to get the next page; null on the last page."""
    total: int
    """How many of the library's grants match the filters, across every page."""
    caller_role: Literal["admin", "creator"]
    """The caller's own role on the library. Only a `creator` (or an operator) gives, changes
    or removes an `admin` and transfers the library."""
    creator: str | None
    """The username of the library's creator, whatever the filters; null for a library that has
    none (one added before roles, which operators manage)."""

    @classmethod
    def from_page(
        cls,
        page: Page[LibraryGrantSummary],
        *,
        caller_role: Literal["admin", "creator"],
        creator: str | None,
    ) -> Self:
        """Wrap a page of grants.

        Args:
            page: The grants and the cursor of the next page.
            caller_role: The caller's role on the library.
            creator: The creator's username, if the library has one.

        Returns:
            The page at the boundary.
        """
        return cls(
            grants=list(page.items),
            next_cursor=page.next_cursor,
            total=page.total or 0,
            caller_role=caller_role,
            creator=creator,
        )


class LibraryCreationQuery(_Dto):
    """Ask whether an authenticated caller may create libraries on this instance."""

    account_id: str
    """The stable account ID."""
    external_identity: ExternalTokenIdentity | None = None
    """Trusted verified request identity; never client arguments."""


_Change = Literal[
    "library_created", "granted", "revoked", "ownership_transferred", "library_deleted"
]


class LibraryAccessLogQuery(_Dto):
    """How a page of one library's access log is filtered and paged (newest first)."""

    limit: Annotated[int, Field(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT
    """How many events per page."""
    cursor: str | None = None
    """Opaque: only ever a `next_cursor`; absent for the first page. It only works with the
    filters of the request that returned it."""
    offset: Annotated[int, Field(ge=0, le=MAX_OFFSET)] | None = None
    """Jump to a page: skip this many matches, in the order and with the filters of the cursor
    walk. Not with `cursor`; the page's `next_cursor` goes on from it."""
    change: list[_Change] | None = Field(
        default=None, description="Only events of these changes; repeat for several."
    )
    """Only events of these changes."""


class AccessLogQuery(LibraryAccessLogQuery):
    """How a page of the instance's access log is filtered and paged (newest first)."""

    library: _LibraryId | None = None
    """Only the events of this library (`/owner/repo`, any case), removed ones included."""


class ListLibraryAccessLogQuery(LibraryAccessLogQuery):
    """Read one library's access log, asked by a caller."""

    caller_id: str
    """The account that asks."""
    library: str
    """The library ID."""


class ListAccessLogQuery(AccessLogQuery):
    """Read the instance's access log, asked by a caller."""

    caller_id: str
    """The account that asks."""


class AccessEventSummary(_Dto):
    """One entry of the access log as the outside world sees it."""

    id: str
    """The event's ID."""
    library: str
    """The library ID (`/owner/repo`, lower-case)."""
    at: datetime
    """When it happened."""
    actor: str | None
    """The username of who made the change; null when the instance did (CLI, a job)."""
    change: _Change
    """What happened: `library_created`, `granted` (a new role, or another one than before),
    `revoked`, `ownership_transferred` or `library_deleted`."""
    kind: Literal["user", "group"] | None
    """Whether `subject` is a username or a group name; null for a deletion."""
    subject: str | None
    """The username or group name the change is about; null for a deletion. An
    `ownership_transferred` event names the new creator."""
    role: str | None
    """The role given, or the role taken away (`revoked`); null for a deletion."""
    previous_role: str | None
    """The role the subject held before; null when it held none."""

    @classmethod
    def from_model(cls, event: AccessEvent, *, actor: str | None, subject: str | None) -> Self:
        """Map an event to its boundary representation.

        Args:
            event: The event.
            actor: What to show as its actor (a username, not an account ID).
            subject: What to show as its subject (a user's name, not its ID).

        Returns:
            Its summary.
        """
        return cls(
            id=event.id,
            library=event.library,
            at=event.at,
            actor=actor,
            change=event.change.value,
            kind=None if event.kind is None else event.kind.value,
            subject=subject,
            role=None if event.role is None else event.role.value,
            previous_role=None if event.previous_role is None else event.previous_role.value,
        )


class AccessLogPage(_Dto):
    """A page of the access log, newest first."""

    events: list[AccessEventSummary]
    """The events of this page."""
    next_cursor: str | None
    """Pass as `cursor` to get the next (older) page; null on the last page."""
    total: int
    """How many events match the filters, across every page."""
