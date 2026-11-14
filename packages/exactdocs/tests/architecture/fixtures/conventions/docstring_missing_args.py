"""Docstrings that do not list every parameter under `Args:`."""


def no_section(name: str) -> None:  # expect: docstring-missing-args
    """Greet someone."""


def one_missing(name: str, *, loud: bool) -> None:  # expect: docstring-missing-args
    """Greet someone.

    Args:
        name: Who to greet.
    """


def star_args(*parts: str, **options: str) -> None:  # expect: docstring-missing-args
    """Join parts.

    Args:
        *parts: The parts.
    """


def nested_entry_is_not_a_parameter(name: str, depth: int) -> None:  # expect: docstring-missing-args
    """Mention a name only inside another entry.

    Args:
        name: Who, for example
            depth: not a parameter entry, it is indented further.
    """


class Thing:
    """A class."""

    def method(self, value: int) -> None:  # expect: docstring-missing-args
        """``self`` is never listed; ``value`` must be."""

    @classmethod
    def build(cls, size: int) -> None:  # expect: docstring-missing-args
        """``cls`` is never listed; ``size`` must be."""
