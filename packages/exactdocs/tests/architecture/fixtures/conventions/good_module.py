"""Code that follows every convention: no violation is reported."""

import dataclasses
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from dataclasses import dataclass as dc
from typing import ClassVar, NoReturn, overload

from pydantic import BaseModel, ConfigDict, computed_field

__all__ = ["Point", "Query"]
logger_name = "lower case and not Final: not a constant"


@dataclass(frozen=True, slots=True, kw_only=True)
class Point:
    """A point."""

    x: int
    """Horizontal position."""
    y: int = 0
    """Vertical position."""
    LABEL: ClassVar[str] = "class variables are not fields"

    @property
    def norm(self) -> int:
        """Manhattan distance to the origin; a property describes the attribute."""
        return abs(self.x) + abs(self.y)

    def moved(self, dx: int, *, dy: int = 0) -> "Point":
        """Move the point.

        Args:
            dx: Horizontal offset.
            dy: Vertical offset.

        Returns:
            A new point.
        """
        return dataclasses.replace(self, x=self.x + dx, y=self.y + dy)

    @staticmethod
    def parse(text: str) -> "Point":
        """Read ``x,y``.

        Args:
            text: The text.

        Returns:
            The point.
        """
        x, y = text.split(",")
        return Point(x=int(x), y=int(y))


@dataclass(slots=True, kw_only=True)  # conventions: allow-mutable-dataclass -- counts calls
class Counter:
    """A justified mutable dataclass."""

    calls: int = 0
    """Calls so far."""


@dataclass(frozen=True)  # conventions: allow-dict, allow-positional -- pickled by a library
class Legacy:
    """Several markers on one line."""

    value: str
    """The value."""


class Query(BaseModel):
    """A query."""

    model_config = ConfigDict(frozen=True, use_attribute_docstrings=True)

    text: str
    """What to search for."""

    @computed_field
    @property
    def length(self) -> int:
        """Length of ``text``."""
        return len(self.text)


class Subquery(Query):
    """Inherits the config."""

    depth: int = 1
    """How deep to go."""


def fail(reason: str) -> NoReturn:
    """Always raise.

    Args:
        reason: Why.

    Raises:
        RuntimeError: Always.
    """
    raise RuntimeError(reason)


def log(*parts: str, **fields: str) -> None:
    """Log a line.

    Args:
        *parts: Words of the line.
        **fields: Extra key/value pairs.
    """

    def render(_: object) -> None:
        """A nested function with a placeholder parameter."""

    render(parts or fields)


def count(limit: int) -> Iterator[int]:
    """Count up.

    Args:
        limit: Where to stop.

    Yields:
        0, 1, ... up to ``limit``.
    """
    yield from range(limit)


@asynccontextmanager
async def session() -> AsyncIterator[str]:
    """Open a session.

    Yields:
        The session id.
    """
    yield "id"


def make_session() -> object:
    """Build a session factory; its nested generator does not make this one a generator.

    Returns:
        The factory.
    """

    @asynccontextmanager
    async def scoped() -> AsyncIterator[str]:
        """Open a scoped session.

        Yields:
            The session id.
        """
        yield "id"

    return scoped


@overload
def same(value: int) -> int: ...
@overload
def same(value: str) -> str: ...
def same(value: int | str) -> int | str:
    """Return the value unchanged.

    Args:
        value: Anything.

    Returns:
        ``value``.
    """
    return value


def quoted() -> "None":
    """A string annotation of ``None`` returns nothing."""


@dc(frozen=True, slots=True, kw_only=True)
class Aliased:
    """`dataclass` under another name, with every flag."""

    value: int
    """The value."""
