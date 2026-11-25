"""The sign-up form."""

from demo import Model, field_validator


class SignUp(Model):
    """A sign-up request."""

    username: str

    @field_validator("username")
    @classmethod
    def normalize(cls, value):
        return value.strip().lower()
