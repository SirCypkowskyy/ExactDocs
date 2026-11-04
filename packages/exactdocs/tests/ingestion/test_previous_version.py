"""Which earlier version a new import is compared with for renames."""

import pytest

from exactdocs.ingestion.models import ImportedRef, RefKind, previous_version


def tag(ref: str) -> ImportedRef:
    return ImportedRef(ref=ref, kind=RefKind.TAG, commit_sha=ref.ljust(40, "0")[:40])


@pytest.mark.parametrize(
    ("ref", "imported", "expected"),
    [
        ("v1.4.0", ["v1.3.0"], "v1.3.0"),
        ("v1.4.0", ["v1.2.0", "v1.3.0", "v1.10.0"], "v1.3.0"),  # numeric order, not text order
        ("v1.10.0", ["v1.9.0", "v1.2.0"], "v1.9.0"),
        ("2.0", ["1.9.9", "v1.4"], "1.9.9"),  # with or without the `v`, any number of parts
        ("v1.4.0", ["v1.4.0", "v1.3.0"], "v1.4.0"),  # a re-import compares with itself
        ("v1.4.0", ["v1.5.0", "v2.0.0"], None),  # only older versions count
        ("v1.4.0", [], None),
        ("main", ["v1.3.0"], None),  # no order for branches
        ("v1.4.0-rc1", ["v1.3.0"], None),  # nor for pre-releases: nothing is guessed
        ("v1.4.0", ["v1.3.0-rc1", "release-2024"], None),
    ],
)
def test_the_highest_older_numeric_tag_is_the_one_to_compare_with(
    ref: str, imported: list[str], expected: str | None
) -> None:
    found = previous_version(ref, [tag(r) for r in imported])

    assert (found.ref if found else None) == expected


def test_a_branch_that_was_imported_before_is_compared_with_its_earlier_commit() -> None:
    main = ImportedRef(ref="main", kind=RefKind.BRANCH, commit_sha="a" * 40)

    assert previous_version("main", [tag("v1.3.0"), main]) == main


def test_only_tags_are_candidates_for_a_numeric_ref() -> None:
    branch = ImportedRef(ref="1.3", kind=RefKind.BRANCH, commit_sha="a" * 40)

    assert previous_version("v1.4.0", [branch]) is None
