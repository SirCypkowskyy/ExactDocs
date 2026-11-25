import pytest

from exactdocs_kernel import clean_path_prefix, inside


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("/", ""),
        ("docs/api/", "docs/api"),
        ("./docs//api/.", "docs/api"),
        ("/docs/api", "docs/api"),
    ],
)
def test_a_prefix_is_its_plain_segments(raw: str, expected: str) -> None:
    assert clean_path_prefix(raw) == expected


@pytest.mark.parametrize("raw", ["..", "docs/../etc", "docs\\api"])
def test_a_prefix_that_could_leave_the_tree_is_refused(raw: str) -> None:
    with pytest.raises(ValueError, match="plain"):
        clean_path_prefix(raw)


@pytest.mark.parametrize(
    ("path", "prefix", "expected"),
    [
        ("docs/api/client.md", "", True),
        ("docs/api/client.md", "docs/api", True),
        ("docs/api/client.md", "docs", True),
        ("docs/api", "docs/api", True),  # an article named like the prefix
        ("docs/api-old/x.md", "docs/api", False),
        ("docs/ap/x.md", "docs/api", False),
        ("other/docs/api/x.md", "docs/api", False),
    ],
)
def test_a_path_is_inside_a_prefix_by_whole_segments(
    path: str, prefix: str, *, expected: bool
) -> None:
    assert inside(path, prefix) is expected
