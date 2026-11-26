"""A partial update of a contact."""

from pydantic import BaseModel


class ContactPatch(BaseModel):
    """The fields to change."""

    email: str | None = None
    phone: str | None = None
    nickname: str = ""
