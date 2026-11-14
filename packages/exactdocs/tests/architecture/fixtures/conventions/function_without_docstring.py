"""Functions and methods without a docstring, public or private."""

from typing import overload


def public() -> None:  # expect: function-without-docstring
    pass


def _private() -> None:  # expect: function-without-docstring
    pass


def outer() -> None:
    """Has one, but its nested function does not."""

    def inner() -> None:  # expect: function-without-docstring
        pass

    if True:

        def in_a_block() -> None:  # expect: function-without-docstring
            pass


class Thing:
    """A class."""

    def method(self) -> None:  # expect: function-without-docstring
        pass

    async def _helper(self) -> None:  # expect: function-without-docstring
        pass

    def __eq__(self, other: object) -> bool:  # expect: function-without-docstring
        return self is other


@overload
def parse(value: int) -> int: ...
@overload
def parse(value: str) -> str: ...
def parse(value: int | str) -> int | str:  # expect: function-without-docstring
    return value
