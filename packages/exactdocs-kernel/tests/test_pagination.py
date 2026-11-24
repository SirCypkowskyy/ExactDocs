import pytest

from exactdocs_kernel import (
    MAX_OFFSET,
    CursorWithOffsetError,
    InvalidCursorError,
    Sort,
    decode_cursor,
    encode_cursor,
    page_offset,
    paginate,
    sorted_page,
)

KEYS = ["a", "b", "c", "d", "e"]


def walk(limit: int) -> list[list[str]]:
    pages, cursor = [], None
    while True:
        page = paginate(KEYS, key=str, limit=limit, cursor=cursor)
        pages.append(page.items)
        if page.next_cursor is None:
            return pages
        cursor = page.next_cursor


def test_pages_cover_every_item_once_and_the_last_page_has_no_cursor() -> None:
    assert walk(2) == [["a", "b"], ["c", "d"], ["e"]]
    assert walk(5) == [KEYS]


def test_cursor_is_keyset_so_a_deleted_item_does_not_shift_the_next_page() -> None:
    cursor = paginate(KEYS, key=str, limit=2, cursor=None).next_cursor

    page = paginate(["b", "c", "d", "e"], key=str, limit=2, cursor=cursor)

    assert page.items == ["c", "d"]


def test_descending_pages_walk_a_newest_first_list() -> None:
    newest_first = list(reversed(KEYS))
    pages, cursor = [], None
    while True:
        page = paginate(newest_first, key=str, limit=2, cursor=cursor, descending=True)
        pages.append(page.items)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor

    assert pages == [["e", "d"], ["c", "b"], ["a"]]


@pytest.mark.parametrize("cursor", ["!!!", "/w", "not a cursor"])
def test_foreign_cursor_is_rejected(cursor: str) -> None:
    with pytest.raises(InvalidCursorError):
        paginate(KEYS, key=str, limit=2, cursor=cursor)


@pytest.mark.parametrize(
    "cursor",
    [
        pytest.param("AA", id="only NUL"),
        pytest.param("YQBi", id="NUL inside"),
        pytest.param(encode_cursor("job-\x00"), id="NUL at the end"),
    ],
)
def test_a_cursor_whose_key_holds_nul_is_rejected(cursor: str) -> None:
    # no key we encode holds NUL; PostgreSQL text would refuse it with a server error
    with pytest.raises(InvalidCursorError):
        decode_cursor(cursor)


@pytest.mark.parametrize("key", ["job-1", "żółw", "\U0010ffff", "a b/c"])
def test_a_cursor_decodes_to_the_key_it_was_encoded_from(key: str) -> None:
    assert decode_cursor(encode_cursor(key)) == key


@pytest.mark.parametrize("limit", [0, -1, 201])
def test_limit_outside_bounds_is_a_programming_error(limit: int) -> None:
    with pytest.raises(ValueError, match="limit"):
        paginate(KEYS, key=str, limit=limit, cursor=None)


# ---------------------------------------------------------------- offset (#509)

WORDS = ["kiwi", "Apple", "fig", "banana", "cherry", "date", "elder"]
"""Several share a length, so the tie-breaker (the word) orders them."""


def sorted_words(limit: int, *, cursor: str | None = None, offset: int | None = None):
    return sorted_page(
        WORDS,
        sort=Sort(field="length", descending=True),
        key_field="word",
        values={"length": len, "word": str},
        key=str,
        limit=limit,
        cursor=cursor,
        offset=offset,
    )


def cursor_walk(limit: int) -> list[str]:
    found, cursor = [], None
    while True:
        page = sorted_words(limit, cursor=cursor)
        found += page.items
        if (cursor := page.next_cursor) is None:
            return found


@pytest.mark.parametrize("limit", [1, 2, 3, 7])
def test_a_page_at_an_offset_is_the_slice_of_the_cursor_walk(limit: int) -> None:
    walked = cursor_walk(limit)

    for offset in range(len(WORDS) + 2):
        page = sorted_words(limit, offset=offset)

        assert page.items == walked[offset : offset + limit], offset
        assert page.total == len(WORDS)
        assert (page.next_cursor is None) == (offset + limit >= len(WORDS))


def test_the_cursor_of_a_page_at_an_offset_goes_on_from_its_last_item() -> None:
    walked = cursor_walk(2)
    page = sorted_words(2, offset=3)

    assert page.next_cursor is not None
    assert sorted_words(2, cursor=page.next_cursor).items == walked[5:7]


def test_an_offset_past_the_end_is_an_empty_last_page_with_the_total() -> None:
    page = sorted_words(5, offset=MAX_OFFSET)

    assert (page.items, page.next_cursor, page.total) == ([], None, len(WORDS))


def test_offset_zero_is_the_first_page() -> None:
    assert sorted_words(3, offset=0) == sorted_words(3)


def test_a_page_never_starts_after_a_cursor_and_at_an_offset() -> None:
    cursor = sorted_words(2).next_cursor

    with pytest.raises(CursorWithOffsetError) as caught:
        sorted_words(2, cursor=cursor, offset=0)

    assert caught.value.code == "cursor_with_offset"
    with pytest.raises(CursorWithOffsetError):
        page_offset(cursor="anything", offset=4)


@pytest.mark.parametrize(
    ("cursor", "offset", "skipped"),
    [
        (None, None, 0),
        ("YQ", None, 0),
        (None, 0, 0),
        (None, 40, 40),
        (None, MAX_OFFSET, MAX_OFFSET),
    ],
)
def test_a_page_skips_its_offset_or_nothing(
    cursor: str | None, offset: int | None, skipped: int
) -> None:
    assert page_offset(cursor=cursor, offset=offset) == skipped


@pytest.mark.parametrize("offset", [-1, MAX_OFFSET + 1])
def test_offset_outside_bounds_is_a_programming_error(offset: int) -> None:
    with pytest.raises(ValueError, match="offset"):
        sorted_words(2, offset=offset)
