"""IDs, refs, the default-version rule and short-SHA lookup: pure model tests."""

import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from exactdocs.catalog.constants import MAX_CLOSE_MATCHES
from exactdocs.catalog.errors import (
    AmbiguousCommitError,
    DuplicateRenameError,
    DuplicateVersionRefError,
    InvalidArticlePathError,
    InvalidCommitShaError,
    InvalidImportTimeError,
    InvalidLibraryIdError,
    InvalidSettingsError,
    InvalidSimilarityError,
    InvalidVersionRefError,
)
from exactdocs.catalog.models import (
    ChunkingConfig,
    HostKind,
    Library,
    LibraryId,
    Manifest,
    ManifestId,
    ManifestRename,
    ParsedId,
    RefKind,
    Version,
    VersionRef,
    close_paths,
)

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def version(ref: str, kind: RefKind = RefKind.TAG, *, sha: str = "a", age_days: int = 0) -> Version:
    """A version imported `age_days` before NOW; `sha` is the start of its 40-character SHA."""
    return Version(
        ref=VersionRef(ref),
        kind=kind,
        commit_sha=sha.ljust(40, "0"),
        imported_at=NOW - timedelta(days=age_days),
    )


def library(*versions: Version, default_branch: str | None = "main") -> Library:
    return Library(
        id=LibraryId("/acme/payments"),
        title="Payments",
        source_url="https://github.com/acme/payments",
        host=HostKind.GITHUB,
        default_branch=None if default_branch is None else VersionRef(default_branch),
        versions=frozenset(versions),
    )


@pytest.mark.parametrize(
    ("text", "library_id", "ref"),
    [
        ("/acme/payments", "/acme/payments", None),
        ("/acme/payments/v1.4.0", "/acme/payments", "v1.4.0"),
        ("/acme/payments/release/1.4", "/acme/payments", "release/1.4"),
        ("/Acme/Payments", "/acme/payments", None),
        ("/Acme/Payments/V1.4.0", "/acme/payments", "V1.4.0"),
        ("/a.b/c_d-e/feature/X/y", "/a.b/c_d-e", "feature/X/y"),
    ],
)
def test_parsing_splits_the_library_from_the_ref(
    text: str, library_id: str, ref: str | None
) -> None:
    parsed = ParsedId.parse(text)

    assert parsed.library == LibraryId(library_id)
    assert parsed.ref == (VersionRef(ref) if ref else None)


@pytest.mark.parametrize(
    "text",
    [
        *("", "/", "acme/payments", "/acme", "/acme/", "//payments", "/acme/pay ments"),
        *("/ac$me/x", "/acme/pay/ments", "/acme/\u00e4", "/./payments", "/acme/.."),
        "/kelvin/\u212a",  # lower-cases to an ASCII `k`, but is not one
    ],
)
def test_a_malformed_library_id_is_a_validation_error(text: str) -> None:
    with pytest.raises(InvalidLibraryIdError):
        LibraryId(text)


@pytest.mark.parametrize(
    "text", ["/acme", "/acme/", "/acme/pay ments", "//x/y", "acme/payments/v1"]
)
def test_a_malformed_id_does_not_parse(text: str) -> None:
    with pytest.raises(InvalidLibraryIdError):
        ParsedId.parse(text)


@pytest.mark.parametrize("text", ["/acme/payments/", "/acme/payments//v1", "/acme/payments/ v1"])
def test_a_malformed_ref_after_the_library_does_not_parse(text: str) -> None:
    with pytest.raises(InvalidVersionRefError):
        ParsedId.parse(text)


def test_library_ids_compare_case_insensitively_and_refs_do_not() -> None:
    assert LibraryId("/Acme/Payments") == LibraryId("/acme/payments")
    assert str(LibraryId("/Acme/Payments")) == "/acme/payments"
    assert VersionRef("V1.4.0") != VersionRef("v1.4.0")


@pytest.mark.parametrize(
    "text",
    [
        *("", " ", "a//b", "/a", "a/", "a b", "a\tb"),
        *("..", "a..b", "a/../b", "-rf", "-", "v1\x00", "v1\x7f", "a\nb", "v1.lock", "a.lock/b"),
        *("a/b.lock", "v\u0085", "v1\u200b"),
    ],
)
def test_a_blank_or_gappy_ref_is_invalid(text: str) -> None:
    with pytest.raises(InvalidVersionRefError):
        VersionRef(text)


@pytest.mark.parametrize("sha", ["", "abc1234", "A" * 40, "g" * 40, "a" * 41])
def test_a_commit_sha_is_a_full_lower_case_hex_id(sha: str) -> None:
    with pytest.raises(InvalidCommitShaError):
        Version(ref=VersionRef("v1"), kind=RefKind.TAG, commit_sha=sha, imported_at=NOW)


@pytest.mark.parametrize(
    ("versions", "default_branch", "expected"),
    [
        # the highest stable semver tag wins, not the newest import or the branch
        (
            [
                version("v1.3.0"),
                version("v1.4.0"),
                version("v1.5.0-rc.1"),
                version("main", RefKind.BRANCH),
            ],
            "main",
            "v1.4.0",
        ),
        ([version("1.9.0"), version("v1.10.0"), version("v1.2.0", age_days=-5)], "main", "v1.10.0"),
        ([version("v2.0.0+build.5"), version("v1.9.9")], None, "v2.0.0+build.5"),
        # pre-releases are never the default while a stable tag exists, and never beat one
        ([version("v1.0.0"), version("v2.0.0-beta.1"), version("v2.0.0-rc.2")], "main", "v1.0.0"),
        # a branch or commit named like a version is not a tag
        ([version("v9.9.9", RefKind.BRANCH), version("v1.0.0")], "main", "v1.0.0"),
        # no stable tag: the default branch, even when it is the oldest import
        (
            [version("v1.0.0-rc.1"), version("main", RefKind.BRANCH, age_days=30)],
            "main",
            "main",
        ),
        (
            [version("dev", RefKind.BRANCH), version("main", RefKind.BRANCH, age_days=9)],
            "main",
            "main",
        ),
        # no stable tag and no default-branch version: the most recently imported one
        (
            [version("v1.0.0-rc.1", age_days=3), version("dev", RefKind.BRANCH, age_days=1)],
            "main",
            "dev",
        ),
        ([version("v1.0", age_days=2), version("2024.1", age_days=1)], None, "2024.1"),
        ([version("v1.0.0-rc.1", age_days=3), version("dev", RefKind.BRANCH)], None, "dev"),
        ([version("only", RefKind.BRANCH)], None, "only"),
        ([], "main", None),
    ],
)
def test_default_version_table(
    versions: list[Version], default_branch: str | None, expected: str | None
) -> None:
    found = library(*versions, default_branch=default_branch).default_version()

    assert (found.ref.value if found else None) == expected


def test_default_version_does_not_depend_on_import_order() -> None:
    same_time = [version("v1.4.0", sha="a"), version("1.4.0", sha="b")]

    assert library(*same_time).default_version() == library(*reversed(same_time)).default_version()


COMMITS = library(
    version("v1.0.0", sha="fed9876"),
    version("abc1234a", RefKind.COMMIT, sha="abc1234a"),
    version("abc1234b", RefKind.COMMIT, sha="abc1234b"),
    version("def4567", RefKind.COMMIT, sha="def4567890"),
)


@pytest.mark.parametrize(
    ("ref", "found"),
    [
        ("v1.0.0", "v1.0.0"),  # exact
        ("V1.0.0", None),  # refs are case-sensitive
        ("v1.0", None),  # never a prefix match for names
        ("def4567", "def4567"),  # exact ref that is also a SHA
        ("def4567890", "def4567"),  # a prefix of the commit SHA, unique
        ("DEF4567890", "def4567"),  # hex digits are case-insensitive
        ("abc1234a0", "abc1234a"),
        ("def456", None),  # shorter than 7 characters
        ("def4568", None),  # no such commit
        ("fed9876", None),  # only a tag's commit starts with it: commit versions only
    ],
)
def test_a_commit_version_is_found_by_ref_or_a_unique_short_sha(
    ref: str, found: str | None
) -> None:
    result = COMMITS.find_version(VersionRef(ref))

    assert (result.ref.value if result else None) == found


def test_an_ambiguous_short_sha_is_a_validation_error() -> None:
    with pytest.raises(AmbiguousCommitError, match="abc1234"):
        COMMITS.find_version(VersionRef("abc1234"))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"split_level": 0},
        {"split_level": 7},
        {"min_chars": -1},
        {"min_chars": 9, "max_chars": 8},
        {"chunker": ""},
    ],
)
def test_chunking_settings_must_be_in_range(kwargs: dict[str, Any]) -> None:
    with pytest.raises(InvalidSettingsError):
        ChunkingConfig(**kwargs)


@pytest.mark.parametrize(
    "text", ["v1.4.0", "release/1.4", "feature/a.b-c_d", "1.4", "a.lockb", "x-y"]
)
def test_ordinary_refs_are_valid(text: str) -> None:
    assert VersionRef(text).value == text


def test_two_versions_with_the_same_ref_are_rejected() -> None:
    with pytest.raises(DuplicateVersionRefError, match=r"v1\.4\.0"):
        library(version("v1.4.0", sha="a"), version("v1.4.0", sha="b"))


def test_a_version_needs_a_timezone_aware_import_time() -> None:
    with pytest.raises(InvalidImportTimeError):
        Version(
            ref=VersionRef("v1"),
            kind=RefKind.TAG,
            commit_sha="a" * 40,
            imported_at=datetime.fromisoformat("2026-11-04T12:00:00"),  # no time zone
        )


def test_only_ascii_digits_make_a_stable_semver_tag() -> None:
    arabic_four = "v1.\u0664.0"

    found = library(version(arabic_four), version("v1.3.0")).default_version()

    assert found is not None
    assert found.ref.value == "v1.3.0"


def test_refs_of_the_same_commit_are_not_an_ambiguous_short_sha() -> None:
    same = library(
        version("abc1234", RefKind.COMMIT, sha="abc1234"),
        version("aaaaaaaaaa", RefKind.COMMIT, sha="abc1234"),
    )

    found = same.find_version(VersionRef("abc12340"))

    assert found is not None
    assert found.commit_sha.startswith("abc1234")
    assert found.ref.value == "aaaaaaaaaa"  # the smallest ref, so the answer is stable


def test_close_paths_prefer_the_same_file_name_then_typos_and_stop_at_five() -> None:
    paths = [
        "api/install.md",
        "docs/guide/install.md",
        *(f"docs/guide/instal{i}.md" for i in range(9)),
    ]

    found = close_paths("docs/guide/instal.md", paths)

    assert len(found) == MAX_CLOSE_MATCHES
    assert close_paths("install.md", paths)[:2] == ["api/install.md", "docs/guide/install.md"]
    assert close_paths("zzz/qqq.txt", []) == []


def test_close_paths_name_the_paths_sharing_words_when_nothing_is_a_typo() -> None:
    # #573: gpt-oss asked pydantic v1.10.22 for an example file the docs only include.
    paths = [
        "docs/index.md",
        "docs/install.md",
        "docs/usage/models.md",
        "docs/usage/model_config.md",
        "docs/usage/validators.md",
        "docs/usage/exporting_models.md",
    ]

    found = close_paths("tmp_examples/models_orm_mode.md", paths)

    assert found[0] == "docs/usage/models.md"  # the file name's word counts double
    assert set(found) == {
        "docs/usage/models.md",
        "docs/usage/model_config.md",
        "docs/usage/exporting_models.md",
    }


def test_close_paths_always_name_some_paths_of_a_version_that_has_any() -> None:
    paths = ["guide/install.md", "api/client.md"]

    assert sorted(close_paths("zzz/qqq.txt", paths)) == sorted(paths)
    assert close_paths("zzz/qqq.txt", paths, limit=1) in (["guide/install.md"], ["api/client.md"])


def test_close_paths_on_a_large_tree_stay_fast_and_bounded() -> None:
    paths = [f"docs/section{i % 50}/page-{i}.md" for i in range(10_000)]
    started = time.perf_counter()

    found = close_paths("docs/section7/page-4999.mdx", paths)

    assert len(found) <= MAX_CLOSE_MATCHES
    assert time.perf_counter() - started < 1.0  # ~0.3 s for 50k unfiltered; a miss must stay cheap


def move(old: str = "a.md", new: str = "b.md", similarity: int = 100) -> ManifestRename:
    return ManifestRename(
        from_ref=VersionRef("v1"), old_path=old, new_path=new, similarity=similarity
    )


@pytest.mark.parametrize("similarity", [0, 101, -5])
def test_a_rename_keeps_a_percentage_of_the_content(similarity: int) -> None:
    with pytest.raises(InvalidSimilarityError):
        move(similarity=similarity)


@pytest.mark.parametrize("path", ["", "../a.md", "a//b.md", "./a.md"])
def test_a_rename_needs_two_article_paths(path: str) -> None:
    with pytest.raises(InvalidArticlePathError):
        move(old=path)
    with pytest.raises(InvalidArticlePathError):
        move(new=path)


def test_a_manifest_renames_a_path_once() -> None:
    with pytest.raises(DuplicateRenameError):
        Manifest(
            id=ManifestId("m"),
            library=LibraryId("/acme/payments"),
            ref=VersionRef("v2"),
            kind=RefKind.TAG,
            commit_sha="a" * 40,
            created_at=NOW,
            renames=(move(), move(new="c.md")),
        )


def test_a_pinned_version_is_the_default_even_with_a_higher_stable_tag() -> None:
    found = replace(
        library(version("v1.3.0"), version("v1.5.0"), version("main", RefKind.BRANCH)),
        pinned_version=VersionRef("v1.3.0"),
    )

    assert found.default_version() == version("v1.3.0")
    assert found.default_is_pinned()


@pytest.mark.parametrize("pinned", [None, "v1.4.0"])  # unpinned, or a pin no version answers to
def test_without_a_usable_pin_the_default_follows_the_rule(pinned: str | None) -> None:
    found = replace(
        library(version("v1.3.0"), version("v1.5.0")),
        pinned_version=None if pinned is None else VersionRef(pinned),
    )

    assert found.default_version() == version("v1.5.0")
    assert not found.default_is_pinned()
