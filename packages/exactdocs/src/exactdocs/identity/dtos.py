"""Data crossing the identity boundary (into and out of driving ports). Immutable, validated."""

from datetime import datetime
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr, model_validator

from exactdocs.identity.constants import (
    MAX_PASSWORD_LENGTH,
    MAX_TOKEN_NAME_INPUT,
    MAX_USERNAME_LENGTH,
    MIN_PASSWORD_LENGTH,
    NEW_PASSWORD_DESCRIPTION,
    NEW_USERNAME_DESCRIPTION,
    TOKEN_NAME_DESCRIPTION,
    USERNAME_DESCRIPTION,
)
from exactdocs.identity.models import Account, ApiToken


class _Dto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


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


class LoginForTokenCommand(_Dto):
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

    @classmethod
    def from_model(cls, account: Account) -> Self:
        """Map a domain entity to its boundary representation.

        Args:
            account: The account.

        Returns:
            Its summary, with when it was created and whether it is disabled.
        """
        return cls(
            id=account.id,
            username=account.username.value,
            role=account.role.value,
            created_at=account.created_at,
            disabled=account.is_disabled,
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


class SessionState(_Dto):
    """What the UI needs to know first: is setup due, is anyone signed in, and who."""

    state: Literal["setup_required", "signed_out", "signed_in"]
    """`setup_required` while no account exists, else whether the caller is signed in."""
    account: AccountSummary | None = None
    """The signed-in account; `null` unless `state` is `signed_in`."""


class CreateTokenCommand(_Dto):
    """A new API token for the caller. ``expires_at`` (timezone-aware) is optional."""

    name: str = Field(max_length=MAX_TOKEN_NAME_INPUT, description=TOKEN_NAME_DESCRIPTION)
    """Label of the new token; its schema description is ``TOKEN_NAME_DESCRIPTION``."""
    expires_at: AwareDatetime | None = None
    """When the token stops working (in the future, with a timezone); omit it for no expiry."""


class TokenSummary(_Dto):
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
        )


class TokenList(_Dto):
    """The caller's tokens, newest first."""

    tokens: list[TokenSummary]
    """The tokens, newest first."""


class TokenGrant(TokenSummary):
    """A new token. ``token`` is the only copy of the secret and is never shown again."""

    token: str = Field(repr=False)
    """The token's secret, shown only this once: send it as `Authorization: Bearer <token>`."""
