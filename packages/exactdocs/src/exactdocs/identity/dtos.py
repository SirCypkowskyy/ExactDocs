"""Data crossing the identity boundary (into and out of driving ports). Immutable, validated."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from exactdocs.identity.constants import (
    MAX_PASSWORD_LENGTH,
    MAX_RETURN_TO_LENGTH,
    MAX_TOKEN_NAME_INPUT,
    MAX_USERNAME_LENGTH,
    MIN_PASSWORD_LENGTH,
    NEW_PASSWORD_DESCRIPTION,
    NEW_USERNAME_DESCRIPTION,
    TOKEN_NAME_DESCRIPTION,
    USERNAME_DESCRIPTION,
)
from exactdocs.identity.models import Account, ApiToken, LibraryGrant, LibraryRole, SignInPolicy
from exactdocs_kernel import LIBRARY_ID_PATTERN, MAX_NAME


class _Dto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class _LibrarySelection(_Dto):
    """An optional, canonical selection of libraries; an empty selection allows none."""

    library_ids: (
        frozenset[Annotated[str, Field(pattern=LIBRARY_ID_PATTERN, max_length=MAX_NAME)]] | None
    ) = None
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


class AccountSummary(_Dto):
    """An account as the outside world sees it (never the password hash)."""

    id: str
    """Stable identifier of the account."""
    username: str
    """The login name, normalised (NFKC, trimmed, case-folded): `Admin` signs in as `admin`."""
    role: str
    """What the account may do: `admin` (an operator, who also manages accounts) or `user`."""

    @classmethod
    def from_model(cls, account: Account) -> Self:
        """Map a domain entity to its boundary representation.

        Args:
            account: The account.

        Returns:
            Its summary.
        """
        return cls(id=account.id, username=account.username.value, role=account.role.value)


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
    """The sign-in provider the account signs in through; `null` for a local account (password)."""
    groups: list[str] = Field(default_factory=list)
    """The account's groups at its identity provider, as of its latest sign-in or revalidation
    (with the provider's `group_prefix`); empty for a local account."""

    @classmethod
    def from_model(
        cls, account: Account, *, provider: str | None = None, groups: list[str] | None = None
    ) -> Self:
        """Map a domain entity to its boundary representation.

        Args:
            account: The account.
            provider: The provider of an external account.
            groups: The groups of an external account.

        Returns:
            Its summary, with when it was created, whether it is disabled, and where it signs
            in.
        """
        return cls(
            id=account.id,
            username=account.username.value,
            role=account.role.value,
            created_at=account.created_at,
            disabled=account.is_disabled,
            provider=provider,
            groups=groups or [],
        )


class UserList(_Dto):
    """Every local account, oldest first."""

    users: list[UserSummary]
    """The accounts, oldest first."""


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


class TokenList(_Dto):
    """The caller's tokens, newest first."""

    tokens: list[TokenSummary]
    """The tokens, newest first."""


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


class ListLibraryGrantsQuery(_Dto):
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


class LibraryCreationQuery(_Dto):
    """Ask whether an authenticated caller may create libraries on this instance."""

    account_id: str
    """The stable account ID."""
    external_identity: ExternalTokenIdentity | None = None
    """Trusted verified request identity; never client arguments."""
