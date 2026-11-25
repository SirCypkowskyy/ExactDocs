"""An article's tags, stored as a JSON list of strings."""

from typing import List

from pydantic import BaseModel, validator


class Tags(BaseModel):
    """A list of unique, lowercase tags."""

    __root__: List[str]

    @validator("__root__")
    def normalize(cls, tags: List[str]) -> List[str]:
        unique: List[str] = []
        for tag in tags:
            tag = tag.lower()
            if tag not in unique:
                unique.append(tag)
        return unique


def parse_tags(text: str) -> Tags:
    """Read tags from their JSON form."""
    return Tags.parse_raw(text)


def dump_tags(tags: Tags) -> str:
    """Write tags as their JSON form."""
    return tags.json()
