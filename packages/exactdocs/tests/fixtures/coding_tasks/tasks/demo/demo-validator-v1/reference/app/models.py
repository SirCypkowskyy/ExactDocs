"""The sign-up form."""

from demo import Model, validator


class SignUp(Model):
    """A sign-up request."""

    username: str

    @validator("username")
    def normalize(cls, value):
        return value.strip().lower()
