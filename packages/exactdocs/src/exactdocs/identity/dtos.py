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
    username: str
    role: str

    @classmethod
    def from_model(cls, account: Account) -> Self:
        """Map a domain entity to its boundary representation."""
        return cls(id=account.id, username=account.username.value, role=account.role.value)


class SetupState(_Dto):
    """Whether the instance still waits for its first admin."""

    setup_required: bool


class CreateFirstAdminCommand(_Dto):
    """The first admin's credentials. The password is a ``SecretStr``: never shown in a repr."""

    username: str
    password: SecretStr = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class AuthenticateQuery(_Dto):
    """A username and password to check."""

    username: str = Field(max_length=4 * MAX_USERNAME_LENGTH)  # cap the input before normalising
    password: SecretStr = Field(max_length=MAX_PASSWORD_LENGTH)


class LoginForTokenCommand(_Dto):
    """Credentials exchanged for an API token (the CLI's login); ``name`` labels the token."""

    username: str = Field(max_length=4 * MAX_USERNAME_LENGTH)
    password: SecretStr = Field(max_length=MAX_PASSWORD_LENGTH)
    name: str = Field(max_length=4 * MAX_TOKEN_NAME_LENGTH)
    expires_at: AwareDatetime | None = None


class ResetPasswordCommand(_Dto):
    """A new password for an existing account (the operator's recovery path)."""

    username: str
    password: SecretStr = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


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
    account: AccountSummary
    max_age: int
    """Seconds until the session cannot be used any more, even if never idle."""


class SessionState(_Dto):
    """What the UI needs to know first: is setup due, is anyone signed in, and who."""

    state: Literal["setup_required", "signed_out", "signed_in"]
    account: AccountSummary | None = None


class CreateTokenCommand(_Dto):
    """A new API token for the caller. ``expires_at`` (timezone-aware) is optional."""

    name: str = Field(max_length=4 * MAX_TOKEN_NAME_LENGTH)  # cap the input before validating
    expires_at: AwareDatetime | None = None


class TokenSummary(_Dto):
    """A token as listed: everything but the secret."""

    id: str
    name: str
    prefix: str
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None

    @classmethod
    def from_model(cls, token: ApiToken) -> Self:
        """Map a domain entity to its boundary representation."""
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


class TokenGrant(TokenSummary):
    """A new token. ``token`` is the only copy of the secret and is never shown again."""

    token: str = Field(repr=False)
