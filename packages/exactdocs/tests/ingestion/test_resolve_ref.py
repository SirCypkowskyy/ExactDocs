import pytest

from exactdocs.ingestion.errors import AmbiguousRefError, UnknownRefError
from exactdocs.ingestion.models import (
    RefKind,
    RemoteRef,
    RemoteRefs,
    ResolvedRef,
    ref_tips,
    resolve_ref,
)

MAIN, NEXT, V13, V14_OBJECT, V14_COMMIT, ABC1, ABC2 = (
    "1" * 40,
    "2" * 40,
    "3" * 40,
    "4" * 40,
    "5" * 40,
    "abc1" + "0" * 36,
    "abc2" + "0" * 36,
)

REFS = RemoteRefs(
    default_branch="main",
    refs=(
        RemoteRef(name="HEAD", sha=MAIN),
        RemoteRef(name="refs/heads/main", sha=MAIN),
        RemoteRef(name="refs/heads/next", sha=NEXT),
        RemoteRef(name="refs/heads/release/1.4", sha=ABC1),
        RemoteRef(name="refs/tags/v1.3.0", sha=V13),
        RemoteRef(name="refs/tags/v1.4.0", sha=V14_OBJECT),  # annotated: the tag object...
        RemoteRef(name="refs/tags/v1.4.0^{}", sha=V14_COMMIT),  # ...and the commit it points at
        RemoteRef(name="refs/heads/bad..name", sha=ABC2),
        RemoteRef(name="refs/pull/1/head", sha="6" * 40),
    ),
)


def pinned(requested: str | None) -> tuple[str, RefKind, str]:
    found = resolve_ref(REFS, requested)
    return found.name, found.kind, found.commit_sha


def test_without_a_ref_the_default_branch_is_pinned_to_its_head() -> None:
    assert pinned(None) == ("main", RefKind.BRANCH, MAIN)


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("next", ("next", RefKind.BRANCH, NEXT)),
        ("release/1.4", ("release/1.4", RefKind.BRANCH, ABC1)),
        ("v1.3.0", ("v1.3.0", RefKind.TAG, V13)),
        ("v1.4.0", ("v1.4.0", RefKind.TAG, V14_COMMIT)),  # an annotated tag gives its commit
        (NEXT, (NEXT, RefKind.COMMIT, NEXT)),
        (NEXT[:7], (NEXT, RefKind.COMMIT, NEXT)),  # short SHAs expand to the full one
        ("ABC1000", (ABC1, RefKind.COMMIT, ABC1)),
        (V14_COMMIT[:12], (V14_COMMIT, RefKind.COMMIT, V14_COMMIT)),
    ],
)
def test_a_ref_is_pinned_to_a_commit(requested: str, expected: tuple[str, RefKind, str]) -> None:
    assert pinned(requested) == expected


@pytest.mark.parametrize(
    "requested", ["v9.9.9", "Main", "v1.4", "222222", "9" * 40, V14_OBJECT, "refs/pull/1/head"]
)
def test_an_unknown_ref_is_refused(requested: str) -> None:
    with pytest.raises(UnknownRefError):
        resolve_ref(REFS, requested)


def test_too_short_a_sha_is_unknown() -> None:
    with pytest.raises(UnknownRefError):
        resolve_ref(REFS, "abc100")


def test_a_short_sha_that_starts_two_commits_is_ambiguous() -> None:
    refs = RemoteRefs(
        default_branch="main",
        refs=(
            RemoteRef(name="refs/heads/main", sha="abcdef0" + "1" * 33),
            RemoteRef(name="refs/heads/other", sha="abcdef0" + "2" * 33),
        ),
    )

    with pytest.raises(AmbiguousRefError):
        resolve_ref(refs, "abcdef0")
    assert resolve_ref(refs, "abcdef01").commit_sha == "abcdef0" + "1" * 33


def test_an_empty_repository_has_no_default_ref() -> None:
    with pytest.raises(UnknownRefError):
        resolve_ref(RemoteRefs(default_branch=None), None)


def test_tips_list_branches_then_tags_sorted_and_skip_foreign_refs() -> None:
    assert ref_tips(REFS) == (
        ResolvedRef(name="main", kind=RefKind.BRANCH, commit_sha=MAIN),
        ResolvedRef(name="next", kind=RefKind.BRANCH, commit_sha=NEXT),
        ResolvedRef(name="release/1.4", kind=RefKind.BRANCH, commit_sha=ABC1),
        ResolvedRef(name="v1.3.0", kind=RefKind.TAG, commit_sha=V13),
        ResolvedRef(name="v1.4.0", kind=RefKind.TAG, commit_sha=V14_COMMIT),
    )


def test_a_tag_wins_over_a_branch_of_the_same_name() -> None:
    refs = RemoteRefs(
        default_branch="main",
        refs=(
            RemoteRef(name="refs/heads/v2", sha=NEXT),
            RemoteRef(name="refs/tags/v2", sha=V13),
        ),
    )

    assert resolve_ref(refs, "v2") == ResolvedRef(name="v2", kind=RefKind.TAG, commit_sha=V13)


def test_a_full_sha_in_capitals_is_the_same_commit() -> None:
    assert pinned(NEXT.upper().replace("2", "2")) == (NEXT, RefKind.COMMIT, NEXT)
    assert pinned(ABC1.upper()) == (ABC1, RefKind.COMMIT, ABC1)


def test_a_tag_named_like_a_sha_prefix_is_the_tag_not_the_commit() -> None:
    refs = RemoteRefs(
        default_branch="main",
        refs=(
            RemoteRef(name="refs/heads/main", sha=ABC1),
            RemoteRef(name="refs/tags/abc1000", sha=V13),
        ),
    )

    assert resolve_ref(refs, "abc1000") == ResolvedRef(
        name="abc1000", kind=RefKind.TAG, commit_sha=V13
    )


@pytest.mark.parametrize("requested", ["refs/heads/next", "refs/tags/v1.3.0", "HEAD"])
def test_fully_qualified_names_are_not_refs(requested: str) -> None:
    with pytest.raises(UnknownRefError):
        resolve_ref(REFS, requested)
