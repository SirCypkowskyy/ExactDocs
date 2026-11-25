"""The sign-up form's data."""

import re

from pydantic import BaseModel, field_validator

USERNAME = re.compile(r"[a-z0-9_]{3,20}")


class SignUp(BaseModel):
    """A sign-up request."""

    username: str
    email: str

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        value = value.strip().lower()
        if not USERNAME.fullmatch(value):
            raise ValueError("username must be 3-20 letters, digits or underscores")
        return value
