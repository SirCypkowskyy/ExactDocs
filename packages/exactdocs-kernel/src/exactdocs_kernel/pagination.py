"""Keyset pagination shared by every list endpoint: ``limit`` plus an opaque ``cursor``."""

from base64 import b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from exactdocs_kernel.errors import ValidationError

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class InvalidCursorError(ValidationError):
    """The cursor was not issued by this API (tampered with, truncated, or from another list)."""

    code = "invalid_cursor"

    def __init__(self) -> None:
        super().__init__("cursor is not valid")


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One page of ``items``; ``next_cursor`` is ``None`` on the last page."""

    items: list[T]
    next_cursor: str | None


def paginate[T](
    items: Sequence[T], *, key: Callable[[T], str], limit: int, cursor: str | None
) -> Page[T]:
    """Return the page of ``items`` after ``cursor``.

    ``items`` must already be sorted ascending by the unique ``key``; the cursor encodes the last
    key served, so inserts and deletes between requests never skip or repeat an item.
    """
    # ponytail: in-memory scan; SQL-backed lists push `key > :after LIMIT :n` into the query.
    after = _decode(cursor) if cursor is not None else None
    rest = [item for item in items if after is None or key(item) > after]
    page, more = rest[:limit], len(rest) > limit
    return Page(page, _encode(key(page[-1])) if more else None)


def _encode(key: str) -> str:
    return urlsafe_b64encode(key.encode()).decode().rstrip("=")


def _decode(cursor: str) -> str:
    try:
        return b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True).decode()
    except Base64Error, UnicodeDecodeError:
        raise InvalidCursorError from None
