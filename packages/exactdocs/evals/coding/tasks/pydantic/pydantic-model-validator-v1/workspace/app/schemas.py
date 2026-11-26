"""Account requests."""

from pydantic import BaseModel


class PasswordChange(BaseModel):
    """A request to change a password."""

    password: str
    confirm: str
