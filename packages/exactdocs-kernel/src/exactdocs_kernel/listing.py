"""Sorting, filtering and cursors shared by every list endpoint: ``sort`` plus a sort-aware cursor.

A list names the fields it may be sorted by (a whitelist); ``sort=-field`` is descending. The
cursor of a sorted page encodes the sort key and the unique key of the last item served, so pages
stay stable under any sort. A sort on the unique key itself keeps the plain key cursor of
``exactdocs_kernel.pagination``.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from exactdocs_kernel.constants import MAX_LIMIT
from exactdocs_kernel.errors import ValidationError
from exactdocs_kernel.pagination import (
    InvalidCursorError,
    Page,
    decode_cursor,
    encode_cursor,
    page_offset,
)

type SortValue = str | int | float
"""What a list is sorted by: text, a number, or an ISO 8601 UTC timestamp (which sorts as text)."""


class InvalidSortError(ValidationError):
    """``sort`` names a field this list cannot be sorted by."""

    code = "invalid_sort"

    def __init__(self, field: str, allowed: Sequence[str]) -> None:
        """Create the error, naming the field and the fields that are allowed.

        Args:
            field: The field as sent.
            allowed: The fields the list can be sorted by.
        """
        super().__init__(
            f"cannot sort by '{field}'; sort by one of: {', '.join(allowed)} "
            "(prefix a field with '-' for descending)"
        )
        self.field = field


class InvalidFilterError(ValidationError):
    """A filter has a value this list does not accept."""

    code = "invalid_filter"

    def __init__(self, field: str, reason: str) -> None:
        """Create the error, naming the filter.

        Args:
            field: The filter's name.
            reason: What is wrong with its value.
        """
        super().__init__(f"filter '{field}': {reason}")
        self.field = field


@dataclass(frozen=True, slots=True, kw_only=True)
class Sort:
    """A validated sort: a whitelisted field and a direction."""

    field: str
    """The field to sort by."""
    descending: bool = False
    """Whether the largest value comes first."""

    @property
    def spec(self) -> str:
        """The sort as the client sends it: ``field`` or ``-field``.

        Returns:
            The spec.
        """
        return f"-{self.field}" if self.descending else self.field


def parse_sort(raw: str | None, *, allowed: Sequence[str], default: str) -> Sort:
    """Validate a ``sort`` parameter against the list's whitelist.

    Args:
        raw: The parameter as sent (``field`` or ``-field``); ``None`` or blank for the default.
        allowed: The fields the list can be sorted by.
        default: The sort used without one, as a spec (``-created_at``).

    Returns:
        The sort.

    Raises:
        InvalidSortError: The field is not in ``allowed``.
    """
    spec = (raw or "").strip() or default
    descending = spec.startswith("-")
    field = spec[1:] if descending else spec
    if field not in allowed:
        raise InvalidSortError(field, allowed)
    return Sort(field=field, descending=descending)


def encode_sort_cursor(sort: Sort, *, key_field: str, value: SortValue, key: str) -> str:
    """Cursor for the last item served by a list sorted by ``sort``.

    Args:
        sort: The list's sort; the cursor is only valid for the same sort.
        key_field: The sort field that is the unique key itself (its cursor is the plain key).
        value: The last item's value of the sort field.
        key: The last item's unique key (the tie-breaker).

    Returns:
        The opaque cursor.
    """
    if sort.field == key_field:
        return encode_cursor(key)
    return encode_cursor(json.dumps([sort.spec, value, key], separators=(",", ":")))


def decode_sort_cursor(cursor: str, sort: Sort, *, key_field: str) -> tuple[SortValue, str]:
    """Return the ``(value, key)`` a cursor stands for.

    Args:
        cursor: A cursor made by ``encode_sort_cursor``.
        sort: The sort of this request; a cursor from another sort is refused.
        key_field: The sort field that is the unique key itself.

    Returns:
        The sort value and the unique key of the last item of the previous page.

    Raises:
        InvalidCursorError: The cursor is malformed or belongs to another sort.
    """
    decoded = decode_cursor(cursor)
    if sort.field == key_field:
        return decoded, decoded
    try:
        spec, value, key = json.loads(decoded)
    except ValueError, TypeError:
        raise InvalidCursorError from None
    if spec != sort.spec or not isinstance(key, str) or isinstance(value, bool):
        raise InvalidCursorError
    if not isinstance(value, str | int | float):
        raise InvalidCursorError
    return value, key


def is_after(item: tuple[SortValue, str], after: tuple[SortValue, str], *, sort: Sort) -> bool:
    """Tell whether an item's ``(sort value, key)`` comes after the cursor's in the sort's order.

    Args:
        item: The item's sort value and unique key.
        after: The cursor's.
        sort: The sort; descending lists go the other way.

    Returns:
        Whether the item belongs on a later page.

    Raises:
        InvalidCursorError: The cursor's value has another type than the sort field's.
    """
    try:
        return item < after if sort.descending else item > after  # ty: ignore[unsupported-operator]
    except TypeError:  # a number where the sort field holds text, or the reverse
        raise InvalidCursorError from None


def sorted_page[T](
    items: Sequence[T],
    *,
    sort: Sort,
    key_field: str,
    values: Mapping[str, Callable[[T], SortValue]],
    key: Callable[[T], str],
    limit: int,
    cursor: str | None,
    offset: int | None = None,
) -> Page[T]:
    """Sort ``items`` and return the page after ``cursor`` (or at ``offset``), counting every item.

    For lists that are small enough to hold in memory (apply any authorization filter first).
    A page at an offset is the slice a walk with cursors reaches, and its ``next_cursor`` goes on
    from its last item.

    Args:
        items: Every item of the list that passed the filters.
        sort: The validated sort.
        key_field: The sort field that is the unique key itself.
        values: The value of each sortable field for an item.
        key: The unique key of an item (the tie-breaker, sorted in the same direction).
        limit: Most items on the page, between 1 and ``MAX_LIMIT``.
        cursor: The ``next_cursor`` of the previous page; ``None`` for the first page.
        offset: How many items to skip instead of a cursor, 0 to ``MAX_OFFSET``; ``None``: none.

    Returns:
        The page, with ``total`` set to the number of ``items``.

    Raises:
        ValueError: ``limit`` or ``offset`` is out of range.
    """
    if not 1 <= limit <= MAX_LIMIT:
        msg = f"limit must be between 1 and {MAX_LIMIT}, got {limit}"
        raise ValueError(msg)
    skip = page_offset(cursor=cursor, offset=offset)
    value_of = values[sort.field]
    ordered = sorted(items, key=lambda i: (value_of(i), key(i)), reverse=sort.descending)
    if cursor is not None:
        after = decode_sort_cursor(cursor, sort, key_field=key_field)
        ordered = [i for i in ordered if is_after((value_of(i), key(i)), after, sort=sort)]
    ordered = ordered[skip:]
    page, more = ordered[:limit], len(ordered) > limit
    last = page[-1] if page else None
    return Page(
        items=page,
        next_cursor=(
            encode_sort_cursor(sort, key_field=key_field, value=value_of(last), key=key(last))
            if more and last is not None
            else None
        ),
        total=len(items),
    )


def like_pattern(text: str) -> str:
    """Return a SQL ``LIKE`` pattern that matches ``text`` anywhere, escaping with a backslash.

    Args:
        text: The text to look for, taken literally.

    Returns:
        ``%text%``, lower-cased, with backslash, percent and underscore escaped.
    """
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped.lower()}%"
