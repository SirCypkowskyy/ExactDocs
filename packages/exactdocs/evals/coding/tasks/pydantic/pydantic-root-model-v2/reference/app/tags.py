"""An article's tags, stored as a JSON list of strings."""

from pydantic import RootModel, field_validator


class Tags(RootModel[list[str]]):
    """A list of unique, lowercase tags."""

    @field_validator("root")
    @classmethod
    def normalize(cls, tags: list[str]) -> list[str]:
        unique: list[str] = []
        for tag in tags:
            tag = tag.lower()
            if tag not in unique:
                unique.append(tag)
        return unique


def parse_tags(text: str) -> Tags:
    """Read tags from their JSON form."""
    return Tags.model_validate_json(text)


def dump_tags(tags: Tags) -> str:
    """Write tags as their JSON form."""
    return tags.model_dump_json()
