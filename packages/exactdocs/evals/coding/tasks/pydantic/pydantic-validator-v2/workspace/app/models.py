"""The sign-up form's data."""

from pydantic import BaseModel


class SignUp(BaseModel):
    """A sign-up request."""

    username: str
    email: str
