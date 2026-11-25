"""A partial update of a contact."""

from pydantic import BaseModel, Field


class ContactPatch(BaseModel):
    """The fields to change."""

    email: str | None = Field(default=None, exclude_if=lambda value: value is None)
    phone: str | None = Field(default=None, exclude_if=lambda value: value is None)
    nickname: str = Field(default="", exclude_if=lambda value: value == "")
