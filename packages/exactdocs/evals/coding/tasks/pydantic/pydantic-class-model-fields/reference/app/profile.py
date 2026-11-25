"""User profiles."""

from pydantic import BaseModel


class Profile(BaseModel):
    """A public profile."""

    name: str
    bio: str = ""
    website: str | None = None

    def changed_fields(self, other: "Profile") -> list[str]:
        """The fields whose values differ from `other`'s, in declaration order."""
        return [
            name
            for name in type(self).model_fields
            if getattr(self, name) != getattr(other, name)
        ]
