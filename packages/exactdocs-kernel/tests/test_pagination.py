import pytest

from exactdocs_kernel import InvalidCursorError, decode_cursor, encode_cursor, paginate

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
