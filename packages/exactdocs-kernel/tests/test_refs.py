import pytest

from exactdocs_kernel import MAX_NAMED_VERSIONS, name_versions, respelled, respelled_note


@pytest.mark.parametrize(
    ("ref", "refs", "expected"),
    [
        ("v1.10.0", ["1.10.0", "0.27.0"], "1.10.0"),
        ("V1.10.0", ["1.10.0"], "1.10.0"),
        ("1.10.0", ["v1.10.0", "v0.27.0"], "v1.10.0"),
        ("1.10.0", ["V1.10.0"], "V1.10.0"),
        ("v2", ["2", "v1"], "2"),
    ],
)
def test_a_ref_finds_the_one_version_it_names_but_for_a_leading_v(
    ref: str, refs: list[str], expected: str
) -> None:
    assert respelled(ref, refs) == expected


@pytest.mark.parametrize(
    ("ref", "refs"),
    [
        ("v1.10.0", ["v1.10.0", "1.10.0"]),  # the ref itself is imported: it is read as given
        ("v1.10.0", ["1.10.0", "V1.10.0"]),  # two spellings imported: neither is guessed
        ("v2.0.0", ["1.10.0", "0.27.0"]),  # another version is never a match
        ("v1.10", ["1.10.0"]),
        ("vnext", ["next"]),  # the letter counts only before a digit
        ("next", ["vnext"]),
        ("MAIN", ["main"]),  # no letter case is forgiven
        ("V1.10.0", ["v1.10.0"]),  # not even the v's: refs are case-sensitive
        ("v1.10.0", ["V1.10.0"]),
        ("vv1.0", ["v1.0", "1.0"]),
        ("v", ["", "v"]),
        ("v1.0", []),
    ],
)
def test_no_ref_or_several_is_none(ref: str, refs: list[str]) -> None:
    assert respelled(ref, refs) is None


def test_the_note_names_both_spellings() -> None:
    assert respelled_note("v1.10.0", "1.10.0") == (
        "ref 'v1.10.0' is not imported: read as '1.10.0', the one version it names but for a "
        "leading v."
    )


def test_the_versions_are_named_newest_first_with_the_default() -> None:
    assert name_versions(["1.10.0", "0.27.0"], "1.10.0") == (
        "imported versions, newest first: '1.10.0', '0.27.0'; default version: '1.10.0'"
    )
    assert name_versions(["main"], None) == "imported versions, newest first: 'main'"
    assert name_versions([], None) == "the library has no imported version"


def test_at_most_twenty_versions_are_named() -> None:
    refs = [f"v1.{n}.0" for n in range(30, 0, -1)]

    named = name_versions(refs, "v1.30.0")

    assert MAX_NAMED_VERSIONS == 20
    assert "'v1.11.0' (and 10 more); default version: 'v1.30.0'" in named
    assert "'v1.10.0'" not in named
