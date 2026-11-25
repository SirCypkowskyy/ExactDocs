import pytest

from exactdocs_kernel import (
    MAX_NAMED_REFS,
    closest_refs,
    leading_v_twin,
    other_v_spelling,
    respelled_note,
)


@pytest.mark.parametrize(
    ("ref", "other"),
    [
        ("v1.10.0", "1.10.0"),
        ("1.10.0", "v1.10.0"),
        ("v2", "2"),
        ("19.1", "v19.1"),
        ("v1.5.0-rc.1", "1.5.0-rc.1"),
        ("2024_01_01", "v2024_01_01"),
    ],
)
def test_a_version_number_is_spelled_with_and_without_its_v(ref: str, other: str) -> None:
    assert other_v_spelling(ref) == other


@pytest.mark.parametrize(
    "ref",
    ["main", "next", "vnext", "v", "V1.0", "vv1.0", "release/1.4", "1234abc", "v1234abc", ""],
)
def test_a_ref_that_is_no_version_number_has_no_other_spelling(ref: str) -> None:
    assert other_v_spelling(ref) is None


@pytest.mark.parametrize(
    ("asked", "refs", "twin"),
    [
        ("v1.10.0", {"0.27.0", "0.52.1", "1.10.0"}, "1.10.0"),
        ("1.4.0", {"v1.3.0", "v1.4.0", "main"}, "v1.4.0"),
        ("v1.10.0", {"v1.10.0", "1.10.0"}, None),  # imported as asked: that one answers
        ("v1.10", {"1.10.0"}, None),  # never another version number
        ("v1.10.1", {"1.10.0"}, None),
        ("V1.10.0", {"1.10.0"}, None),  # only a lower-case v
        ("vnext", {"next"}, None),  # a v that starts no version number is part of the name
        ("v1234abc", {"1234abc"}, None),  # a short SHA is no version number
    ],
)
def test_the_twin_differs_only_by_the_leading_v(
    asked: str, refs: set[str], twin: str | None
) -> None:
    assert leading_v_twin(asked, refs) == twin


def test_a_library_with_few_refs_is_named_whole_most_alike_first() -> None:
    refs = ["0.27.0", "0.52.1", "1.10.0"]

    assert closest_refs("v1.10.1", refs) == ["1.10.0", "0.52.1", "0.27.0"]


def test_without_a_ref_the_refs_come_highest_number_first() -> None:
    assert closest_refs(None, ["1.9.0", "1.10.0", "main", "v1.11.0"]) == [
        "v1.11.0",
        "1.10.0",
        "1.9.0",
        "main",
    ]


def test_a_library_with_many_refs_names_the_closest_few() -> None:
    refs = [f"v1.{minor}.0" for minor in range(40)] + ["main"]

    named = closest_refs("v1.17.0", refs)

    assert len(named) == MAX_NAMED_REFS
    assert named[0] == "v1.17.0"
    assert "main" not in named


def test_closest_refs_names_each_ref_once() -> None:
    assert closest_refs("v2.0.0", ["1.0.0", "1.0.0", "main"]) == ["1.0.0", "main"]


def test_a_note_says_which_spelling_answered() -> None:
    assert respelled_note("v1.10.0", "1.10.0") == (
        "ref 'v1.10.0' is not imported: version '1.10.0', the same number without the leading v, "
        "answered."
    )
    assert respelled_note("1.4.0", "v1.4.0") == (
        "ref '1.4.0' is not imported: version 'v1.4.0', the same number with a leading v, answered."
    )


@pytest.mark.parametrize(
    ("asked", "answered"),
    [("v1.4.0", "v1.4.0"), (None, "v1.4.0"), ("fedcba9", "fedcba98"), ("main", "vmain")],
)
def test_no_note_when_the_ref_answered_as_asked_or_another_did(
    asked: str | None, answered: str
) -> None:
    assert respelled_note(asked, answered) is None
