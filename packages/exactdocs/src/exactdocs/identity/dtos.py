"""Data crossing the identity boundary (into and out of driving ports). Immutable, validated."""

from datetime import datetime
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr

from exactdocs.identity.constants import (
    MAX_PASSWORD_LENGTH,
    MAX_TOKEN_NAME_LENGTH,
    MAX_USERNAME_LENGTH,
    MIN_PASSWORD_LENGTH,
)
from exactdocs.identity.models import Account, ApiToken


class _Dto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class AccountSummary(_Dto):
    """An account as the outside world sees it (never the password hash)."""

    id: str
    """Stable identifier of the account."""
    username: str
    """The login name, normalised: case-folded, so `Admin` signs in as `admin`."""
    role: str
    """What the account may do; `admin` is the only role so far."""

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

    username: str
    """Login name of the first admin: 1 to 64 characters, no whitespace or control characters."""
    password: SecretStr = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    """Password of the first admin, 12 to 1024 characters."""


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
    name: str = Field(max_length=4 * MAX_TOKEN_NAME_LENGTH)
    """Label of the new token, 1 to 64 characters, to tell it apart in the token list."""
    expires_at: AwareDatetime | None = None
    """When the token stops working (in the future, with a timezone); omit it for no expiry."""


class ResetPasswordCommand(_Dto):
    """A new password for an existing account (the operator's recovery path)."""

    username: str
    """Login name of the account, compared case-insensitively."""
    password: SecretStr = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    """The new password, 12 to 1024 characters."""


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
    """The session's secret, shown only this once."""
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

    name: str = Field(max_length=4 * MAX_TOKEN_NAME_LENGTH)  # cap the input before validating
    """Label of the new token, 1 to 64 characters, to tell it apart in the token list."""
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
