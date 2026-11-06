"""Docstrings that do not describe a returned value."""

from collections.abc import Iterator


def total(values: list[int]) -> int:  # expect: docstring-missing-returns
    """Add values up.

    Args:
        values: The numbers.
    """
    return sum(values)


async def fetch() -> str:  # expect: docstring-missing-returns
    """Fetch it."""
    return "it"


def unannotated():  # expect: docstring-missing-returns
    """Return something without saying so."""
    return 1


def numbers() -> Iterator[int]:  # expect: docstring-missing-returns
    """Count up; a generator documents `Yields:`.

    Returns:
        Not the right section for a generator.
    """
    yield 1
