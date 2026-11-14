"""Which earlier version a new import is compared with for renames."""

import pytest

from exactdocs.ingestion.models import (
    GitRename,
    ImportedRef,
    RefKind,
    compose_renames,
    is_unordered,
    previous_version,
)


def tag(ref: str) -> ImportedRef:
    return ImportedRef(ref=ref, kind=RefKind.TAG, commit_sha=ref.ljust(40, "0")[:40])


@pytest.mark.parametrize(
    ("ref", "imported", "expected"),
    [
        ("v1.4.0", ["v1.3.0"], "v1.3.0"),
        ("v1.4.0", ["v1.2.0", "v1.3.0", "v1.10.0"], "v1.3.0"),  # numeric order, not text order
        ("v1.10.0", ["v1.9.0", "v1.2.0"], "v1.9.0"),
        ("2.0", ["1.9.9", "v1.4"], "1.9.9"),  # with or without the `v`, any number of parts
        ("v1.4.0", ["v1.4.0", "v1.3.0"], "v1.3.0"),  # a re-sync never compares with itself
        ("v1.4", ["v1.4.0", "v1.3"], "v1.3"),  # 1.4 and 1.4.0 are one version
        ("v1.4.0", ["v1.4", "v1.3.0"], "v1.3.0"),
        ("v1.4.0", ["v1.3." + "9" * 40], None),  # absurd numbers are no version at all
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


def test_a_numeric_ref_with_absurd_digits_is_not_ordered() -> None:
    assert previous_version("v1." + "9" * 40, [tag("v1.3.0")]) is None


def test_a_branch_that_was_imported_before_is_compared_with_its_earlier_commit() -> None:
    main = ImportedRef(ref="main", kind=RefKind.BRANCH, commit_sha="a" * 40)

    assert previous_version("main", [tag("v1.3.0"), main]) == main


def test_only_tags_are_candidates_for_a_numeric_ref() -> None:
    branch = ImportedRef(ref="1.3", kind=RefKind.BRANCH, commit_sha="a" * 40)

    assert previous_version("v1.4.0", [branch]) is None


def moved(old: str, new: str, similarity: int = 100) -> GitRename:
    return GitRename(old_path=old, new_path=new, similarity=similarity)


def test_only_refs_without_an_order_build_their_map_up() -> None:
    assert [is_unordered(r) for r in ("main", "release/1.4", "a" * 40, "v1.4.0", "2.1")] == [
        True, True, True, False, False,
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("earlier", "latest", "expected"),
    [
        ([moved("a", "b")], [moved("b", "c")], [moved("a", "c"), moved("b", "c")]),
        ([moved("a", "b", 80)], [moved("b", "c", 60)], [moved("a", "c", 60), moved("b", "c", 60)]),
        ([moved("a", "b")], [], [moved("a", "b")]),  # nothing new: the map stays
        ([moved("a", "b")], [moved("x", "y")], [moved("a", "b"), moved("x", "y")]),
        ([moved("a", "gone")], [], []),  # the target is no longer an article
        ([moved("a", "b")], [moved("b", "a")], [moved("b", "a")]),  # back where it began: dropped
        ([moved("a", "b")], [moved("a", "c")], [moved("a", "b")]),  # the old a is the earlier file
    ],
)
def test_a_branch_chains_its_renames_across_syncs(
    earlier: list[GitRename], latest: list[GitRename], expected: list[GitRename]
) -> None:
    articles = {"b", "c", "y", "a"}

    assert compose_renames(earlier, latest, articles) == tuple(expected)
