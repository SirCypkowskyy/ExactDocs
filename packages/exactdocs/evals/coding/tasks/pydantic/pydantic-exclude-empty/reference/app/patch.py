"""A partial update of a contact."""

from typing import Any

from pydantic import BaseModel, SerializerFunctionWrapHandler, model_serializer

EMPTY = {"email": None, "phone": None, "nickname": ""}


class ContactPatch(BaseModel):
    """The fields to change."""

    email: str | None = None
    phone: str | None = None
    nickname: str = ""

    @model_serializer(mode="wrap")
    def _without_empty_values(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data = handler(self)
        return {
            key: value
            for key, value in data.items()
            if key not in EMPTY or value != EMPTY[key]
        }
