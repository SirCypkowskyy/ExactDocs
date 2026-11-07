"""Dataclass and pydantic fields without an attribute docstring."""

from dataclasses import dataclass
from typing import ClassVar

from pydantic import BaseModel, ConfigDict


@dataclass(frozen=True, slots=True, kw_only=True)
class Point:
    """A point."""

    x: int  # expect: field-without-docstring
    y: int
    """Documented."""
    ORIGIN: ClassVar[str] = "class variables are not fields"


class Query(BaseModel):
    """A pydantic model."""

    model_config = ConfigDict(frozen=True, use_attribute_docstrings=True)

    text: str  # expect: field-without-docstring
    limit: int = 10
    """Documented."""


class Subquery(Query):
    """A model through a project-local base."""

    depth: int = 1  # expect: field-without-docstring
