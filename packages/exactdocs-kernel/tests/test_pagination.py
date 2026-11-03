import pytest

from exactdocs_kernel import InvalidCursorError, paginate

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


@pytest.mark.parametrize("cursor", ["!!!", "/w", "not a cursor"])
def test_foreign_cursor_is_rejected(cursor: str) -> None:
    with pytest.raises(InvalidCursorError):
        paginate(KEYS, key=str, limit=2, cursor=cursor)
