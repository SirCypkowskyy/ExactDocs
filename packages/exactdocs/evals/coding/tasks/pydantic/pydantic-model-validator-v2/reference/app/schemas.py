"""Account requests."""

from typing import Self

from pydantic import BaseModel, model_validator


class PasswordChange(BaseModel):
    """A request to change a password."""

    password: str
    confirm: str

    @model_validator(mode="after")
    def passwords_match(self) -> Self:
        if self.password != self.confirm:
            raise ValueError("passwords do not match")
        return self
