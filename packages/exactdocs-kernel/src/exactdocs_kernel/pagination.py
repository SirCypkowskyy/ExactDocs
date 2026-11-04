"""Keyset pagination shared by every list endpoint: ``limit`` plus an opaque ``cursor``."""

from base64 import b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from exactdocs_kernel.errors import ValidationError

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class InvalidCursorError(ValidationError):
    """The cursor is not a well-formed cursor (malformed encoding). It is encoded, not signed."""

    code = "invalid_cursor"

    def __init__(self) -> None:
        super().__init__("cursor is not valid")


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One page of ``items``; ``next_cursor`` is ``None`` on the last page."""

    items: list[T]
    next_cursor: str | None


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
    """
    # ponytail: in-memory scan; SQL-backed lists push `key > :after LIMIT :n` into the query,
    # ordered like Python compares str (SQLite's BINARY collation does for UTF-8).
    if not 1 <= limit <= MAX_LIMIT:
        msg = f"limit must be between 1 and {MAX_LIMIT}, got {limit}"
        raise ValueError(msg)
    after = _decode(cursor) if cursor is not None else None
    rest = [
        item
        for item in items
        if after is None or (key(item) < after if descending else key(item) > after)
    ]
    page, more = rest[:limit], len(rest) > limit
    return Page(page, _encode(key(page[-1])) if more else None)


def _encode(key: str) -> str:
    return urlsafe_b64encode(key.encode()).decode().rstrip("=")


def _decode(cursor: str) -> str:
    try:
        return b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True).decode()
    except Base64Error, UnicodeDecodeError:
        raise InvalidCursorError from None
