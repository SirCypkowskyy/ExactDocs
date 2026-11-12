"""Keyset pagination shared by every list endpoint: ``limit`` plus an opaque ``cursor``."""

from base64 import b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from exactdocs_kernel.constants import MAX_LIMIT
from exactdocs_kernel.errors import ValidationError


class InvalidCursorError(ValidationError):
    """The cursor is not a well-formed cursor (malformed encoding). It is encoded, not signed."""

    code = "invalid_cursor"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("cursor is not valid")


@dataclass(frozen=True, slots=True, kw_only=True)
class Page[T]:
    """One page of ``items``; ``next_cursor`` is ``None`` on the last page."""

    items: list[T]
    """The items on this page, in list order."""
    next_cursor: str | None
    """Opaque cursor to pass back for the next page; ``None`` on the last page."""


def paginate[T](
    items: Sequence[T],
    *,
    key: Callable[[T], str],
    limit: int,
    cursor: str | None,
    descending: bool = False,
) -> Page[T]:
    """Return the page of ``items`` after ``cursor``.

    ``items`` must already be sorted by the unique ``key``, ascending (or descending with
    ``descending=True``, for "newest first" lists over time-ordered keys); the cursor encodes the
    last key served, so inserts and deletes between requests never skip or repeat an item. Apply any
    authorization filter before calling: a cursor only narrows what is passed in.

    Args:
        items: Every item of the list, sorted by ``key``.
        key: The unique sort key of an item.
        limit: Most items on the page, between 1 and ``MAX_LIMIT``.
        cursor: The ``next_cursor`` of the previous page; ``None`` for the first page.
        descending: Whether ``items`` are sorted by ``key`` descending.

    Returns:
        The page, with the cursor to the next one when more items follow.

    Raises:
        ValueError: ``limit`` is out of range.
    """
    # ponytail: in-memory scan; SQL-backed lists push `key > :after LIMIT :n` into the query,
    # ordered like Python compares str (SQLite's BINARY collation does for UTF-8).
    if not 1 <= limit <= MAX_LIMIT:
        msg = f"limit must be between 1 and {MAX_LIMIT}, got {limit}"
        raise ValueError(msg)
    after = decode_cursor(cursor) if cursor is not None else None
    rest = [
        item
        for item in items
        if after is None or (key(item) < after if descending else key(item) > after)
    ]
    page, more = rest[:limit], len(rest) > limit
    return Page(items=page, next_cursor=encode_cursor(key(page[-1])) if more else None)


def encode_cursor(key: str) -> str:
    """Opaque cursor for the last key served (for lists that page in the database).

    Args:
        key: The sort key of the last item served.

    Returns:
        The cursor (URL-safe base64, unpadded).
    """
    return urlsafe_b64encode(key.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> str:
    """Return the key a cursor stands for.

    Args:
        cursor: A cursor made by ``encode_cursor``.

    Returns:
        The sort key it encodes.

    Raises:
        InvalidCursorError: The cursor is malformed.
    """
    try:
        return b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True).decode()
    except Base64Error, UnicodeDecodeError:
        raise InvalidCursorError from None
