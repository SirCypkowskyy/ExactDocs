"""Account requests."""

from pydantic import BaseModel, root_validator


class PasswordChange(BaseModel):
    """A request to change a password."""

    password: str
    confirm: str

    @root_validator(skip_on_failure=True)
    def passwords_match(cls, values: dict) -> dict:
        if values["password"] != values["confirm"]:
            raise ValueError("passwords do not match")
        return values
