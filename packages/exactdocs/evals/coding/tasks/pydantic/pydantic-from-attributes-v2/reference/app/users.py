"""Users as the database returns them, and as the API shows them."""

from pydantic import BaseModel, ConfigDict


class UserRow:
    """A row of the users table (not a Pydantic model)."""

    def __init__(self, id: int, name: str, email: str, password_hash: str) -> None:
        self.id = id
        self.name = name
        self.email = email
        self.password_hash = password_hash


class UserOut(BaseModel):
    """A user as the API shows it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str


def to_api(row: UserRow) -> UserOut:
    """Show a row through the API."""
    return UserOut.model_validate(row)
