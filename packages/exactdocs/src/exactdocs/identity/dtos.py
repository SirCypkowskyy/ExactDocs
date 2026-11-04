"""Data crossing the identity boundary (into and out of driving ports). Immutable, validated."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from exactdocs.identity.models import Account

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1024  # bounds the work a request can make the hasher do


class _Dto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


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

    username: str
    password: SecretStr = Field(max_length=MAX_PASSWORD_LENGTH)
