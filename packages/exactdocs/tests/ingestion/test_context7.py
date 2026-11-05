"""A repository's ``context7.json`` (LIB-06): parsing, and how adding or previewing uses it."""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from exactdocs.ingestion.adapters.driven.memory import InMemoryJobRepository, NoIndex, NoRemovals
from exactdocs.ingestion.dtos import AddLibraryCommand, PreviewRepositoryCommand
from exactdocs.ingestion.errors import (
    InvalidContext7Error,
    PreviewBusyError,
    RepositoryUnreachableError,
)
from exactdocs.ingestion.models import (
    CONTEXT7_MAX_BYTES,
    IMPORT_JOB,
    MAX_CONTEXT7_RULES,
    Context7Config,
    Credential,
    FetchedFile,
    NewLibrary,
    PathSelection,
    PreviousVersion,
    RemoteRef,
    RemoteRefs,
    RepositoryUrl,
    context7_selection,
    parse_context7,
)
from exactdocs.ingestion.module import IngestionModule
from exactdocs_kernel import SystemClock

TIP = "a" * 40
URL = "https://github.com/acme/orders"
FULL = {
    "$schema": "https://context7.com/schema/context7.json",
    "projectTitle": "  Acme\nOrders  ",
    "description": "Order docs.",
    "folders": ["docs", "./guides/"],
    "excludeFolders": ["archive", "./docs/internal"],
    "excludeFiles": ["CHANGELOG.md"],
    "rules": ["Use v2 client", "Use v2 client", "  Always\n pin the SDK "],
    "previousVersions": [{"tag": "v1.0.0", "title": "version 1.0"}, {"tag": "v0.9.0"}],
    "url": "https://context7.com/acme/orders",
}


def as_bytes(document: object) -> bytes:
    return json.dumps(document).encode()


def test_every_key_exactdocs_uses_is_read_and_the_rest_ignored() -> None:
    config = parse_context7(as_bytes(FULL))

    assert config == Context7Config(
        project_title="Acme Orders",
        description="Order docs.",
        folders=("docs", "./guides/"),
        exclude_folders=("archive", "./docs/internal"),
        exclude_files=("CHANGELOG.md",),
        rules=("Use v2 client", "Always pin the SDK"),
        previous_versions=(PreviousVersion("v1.0.0", "version 1.0"), PreviousVersion("v0.9.0")),
        selection=PathSelection.of(
            ["docs/", "guides/"], ["**/archive/", "docs/internal/", "**/CHANGELOG.md"]
        ),
    )


def test_an_empty_object_says_nothing() -> None:
    assert parse_context7(b"\xef\xbb\xbf{}") == Context7Config()


@pytest.mark.parametrize(
    ("path", "selected"),
    [
        ("docs/guide/a.md", True),
        ("guides/b.mdx", True),
        ("README.md", False),  # outside the folders
        ("docs/archive/old.md", False),  # a bare folder name is excluded anywhere
        ("archive/x.md", False),
        ("docs/internal/x.md", False),  # a path only there
        ("docs/x/docs/internal/y.md", True),
        ("docs/CHANGELOG.md", False),  # a bare file name anywhere
        ("docs/notes/CHANGELOG.md.bak", False),  # not an article anyway
    ],
)
def test_folders_and_exclusions_translate_to_a_path_selection(path: str, selected: bool) -> None:
    selection = parse_context7(as_bytes(FULL)).selection

    assert selection is not None
    assert selection.selects(path) is selected


def test_a_root_folder_or_only_exclusions_mean_every_article_but_those() -> None:
    assert context7_selection([".", "docs"], [], []) == PathSelection.of()
    assert context7_selection([], ["**/tmp/**"], []) == PathSelection.of([], ["**/tmp/**"])
    assert context7_selection([], [], []) is None


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"{", "not valid JSON"),
        (b"[" * 100_000 + b"]" * 100_000, "larger than"),
        (b"[]", "not a JSON object"),
        (b"\xff\xfe{}", "not UTF-8"),
        (as_bytes({"folders": "docs"}), "folders must be a list of strings"),
        (as_bytes({"excludeFiles": [1]}), "excludeFiles must be a list of strings"),
        (as_bytes({"projectTitle": 3}), "projectTitle must be a string"),
        (
            as_bytes({"rules": ["a" + chr(0x202E) + "b"]}),
            "rules has control or invisible characters",
        ),
        (as_bytes({"rules": [f"r{i}" for i in range(MAX_CONTEXT7_RULES + 1)]}), "rules: at most"),
        (as_bytes({"rules": ["r" * 501]}), "rules: at most"),
        (as_bytes({"folders": ["../secrets"]}), "folders or excludes"),
        (as_bytes({"previousVersions": "v1"}), "previousVersions must be a list"),
        (as_bytes({"previousVersions": [{"tag": "v1"}] * 51}), "previousVersions must be a list"),
    ],
)
def test_an_unusable_file_is_refused_with_the_reason(data: bytes, reason: str) -> None:
    with pytest.raises(InvalidContext7Error, match=reason):
        parse_context7(data)


def test_deep_nesting_within_the_size_limit_is_refused_not_a_crash() -> None:
    depth = CONTEXT7_MAX_BYTES // 2 - 1

    with pytest.raises(InvalidContext7Error):  # too deep for the parser, or not an object
        parse_context7(b"[" * depth + b"]" * depth)
    with pytest.raises(InvalidContext7Error):
        parse_context7(b'{"rules": ' + b"[" * depth + b"]" * depth + b"}")


def test_unusable_previous_versions_are_dropped_with_a_note_and_the_rest_kept() -> None:
    entries = [
        {"tag": "v1.0.0"},
        {"tag": "--upload-pack=x"},  # would be read as a git option
        {"tag": "v1..2"},
        {"tag": "v 1"},
        {"tag": "a" * 256},
        "v0.9.0",
        {"title": "no tag"},
        {"tag": "v0.8.0", "title": 3},
        {"tag": "release/2.0", "title": "two"},
        {"tag": "@"},  # git refuses the single character @
    ]

    config = parse_context7(as_bytes({"previousVersions": entries}))

    assert config.previous_versions == (
        PreviousVersion("v1.0.0"),
        PreviousVersion("release/2.0", "two"),
    )
    assert len(config.notes) == 8
    assert all(n.startswith("previousVersions: an entry is left out") for n in config.notes)
    assert "'--upload-pack=x'" in config.notes[0]


def test_the_rule_limit_counts_distinct_rules() -> None:
    config = parse_context7(as_bytes({"rules": ["a", "b", "", " "] * 10}))

    assert config.rules == ("a", "b")


def test_a_leading_slash_is_the_repository_root_as_in_context7() -> None:
    config = parse_context7(
        as_bytes({"folders": ["/docs"], "excludeFolders": ["/docs/old"], "excludeFiles": ["/x.md"]})
    )

    assert config.selection == PathSelection.of(["docs/"], ["docs/old/", "x.md"])


@dataclass
class FakeRemote:
    async def host_key_fingerprint(self, repository: RepositoryUrl) -> str | None:
        del repository

    async def list_refs(
        self, repository: RepositoryUrl, *patterns: str, credential: Credential | None = None
    ) -> RemoteRefs:
        del repository, patterns, credential
        return RemoteRefs(default_branch="main", refs=(RemoteRef(name="refs/heads/main", sha=TIP),))


@dataclass
class FakeTree:
    """Plays ``RepositoryTree``: the commit's root holds ``files``."""

    files: dict[str, FetchedFile] = field(default_factory=dict)
    error: Exception | None = None
    asked: list[tuple[str, int]] = field(default_factory=list)

    async def list_files(self, repository: RepositoryUrl, commit_sha: str, **_: object) -> list:
        del repository, commit_sha
        return ["README.md", "docs/a.md", "docs/archive/old.md", "guides/b.md", "src/c.md"]

    async def read_file(
        self,
        repository: RepositoryUrl,
        commit_sha: str,
        path: str,
        *,
        max_bytes: int,
        refs: Sequence[str] = (),
        credential: Credential | None = None,
    ) -> FetchedFile:
        del repository, refs, credential
        assert commit_sha == TIP
        self.asked.append((path, max_bytes))
        if self.error:
            raise self.error
        return self.files.get(path, FetchedFile())


def tree_with(data: bytes) -> FakeTree:
    return FakeTree({"context7.json": FetchedFile(data=data)})


@dataclass
class FakeCatalog:
    added: list[NewLibrary] = field(default_factory=list)

    async def is_taken(self, library_id: str) -> bool:
        del library_id
        return False

    async def add(self, library: NewLibrary) -> str:
        self.added.append(library)
        return library.library_id

    async def discard(self, library_id: str) -> None:
        del library_id


async def _run(job: object, progress: object, /) -> None: ...


def build(tree: FakeTree | None, catalog: FakeCatalog) -> IngestionModule:
    handlers: dict = {IMPORT_JOB: _run}
    return IngestionModule.build(
        jobs=InMemoryJobRepository(),
        clock=SystemClock(),
        remote=FakeRemote(),
        tree=tree,
        library_ids=catalog,
        libraries=catalog,
        removals=NoRemovals(),
        index=NoIndex(),
        handlers=handlers,
    )


@pytest.fixture
def catalog() -> FakeCatalog:
    return FakeCatalog()


async def test_without_paths_the_library_takes_those_of_context7_json(
    catalog: FakeCatalog,
) -> None:
    tree = tree_with(as_bytes(FULL))

    added = await build(tree, catalog).add_library(AddLibraryCommand(url=URL))

    (library,) = catalog.added
    expected = PathSelection.of(
        ["docs/", "guides/"], ["**/archive/", "docs/internal/", "**/CHANGELOG.md"]
    )
    assert library.selection == expected
    assert (added.include_paths, added.exclude_paths) == (
        list(expected.include),
        list(expected.exclude),
    )
    assert added.context7 is not None
    assert added.context7.rules == ["Use v2 client", "Always pin the SDK"]
    assert [(v.tag, v.title) for v in added.context7.previous_versions] == [
        ("v1.0.0", "version 1.0"),
        ("v0.9.0", ""),
    ]
    assert added.context7.notes == []
    assert added.context7_warning is None
    assert tree.asked == [("context7.json", CONTEXT7_MAX_BYTES)]


@pytest.mark.parametrize(
    "command",
    [
        AddLibraryCommand(url=URL, include_paths=["src/"]),
        AddLibraryCommand(url=URL, exclude_paths=["src/"]),
    ],
    ids=["include", "exclude"],
)
async def test_paths_a_user_sends_win_over_context7_json(
    catalog: FakeCatalog, command: AddLibraryCommand
) -> None:
    added = await build(tree_with(as_bytes(FULL)), catalog).add_library(command)

    (library,) = catalog.added
    assert library.selection == PathSelection.of(command.include_paths, command.exclude_paths)
    assert added.context7 is not None  # still reported, e.g. for its previous versions


@pytest.mark.parametrize(
    ("tree", "warning"),
    [
        (FakeTree(), None),
        (tree_with(b"{"), "context7.json is ignored: it is not valid JSON"),
        (
            FakeTree({"context7.json": FetchedFile(problem="larger than 65536 bytes")}),
            "context7.json is ignored: larger than 65536 bytes",
        ),
        (
            FakeTree(error=RepositoryUnreachableError("gone")),
            "context7.json is ignored: it could not be fetched",
        ),
        (
            FakeTree(error=OSError(28, "No space left on device")),
            "context7.json is ignored: it could not be read",
        ),
    ],
    ids=["absent", "invalid", "too-large", "unfetchable", "unexpected"],
)
async def test_a_missing_or_unusable_file_adds_the_library_as_if_there_were_none(
    catalog: FakeCatalog, tree: FakeTree, warning: str | None
) -> None:
    added = await build(tree, catalog).add_library(AddLibraryCommand(url=URL))

    (library,) = catalog.added
    assert library.selection == PathSelection.of()
    assert added.context7 is None
    if warning is None:
        assert added.context7_warning is None
    else:
        assert (added.context7_warning or "").startswith(warning), added.context7_warning


async def test_an_add_without_paths_is_refused_while_every_preview_slot_is_busy(
    catalog: FakeCatalog,
) -> None:
    busy = FakeTree(error=PreviewBusyError(retry_after=5))

    with pytest.raises(PreviewBusyError):
        await build(busy, catalog).add_library(AddLibraryCommand(url=URL))

    assert catalog.added == []  # nothing stored: a retry is not met with a 409


async def test_an_add_with_paths_goes_on_while_every_preview_slot_is_busy(
    catalog: FakeCatalog,
) -> None:
    busy = FakeTree(error=PreviewBusyError(retry_after=5))

    added = await build(busy, catalog).add_library(
        AddLibraryCommand(url=URL, include_paths=["docs/"])
    )

    (library,) = catalog.added
    assert library.selection == PathSelection.of(["docs/"])
    assert added.context7 is None
    assert (added.context7_warning or "").startswith(
        "context7.json is ignored: it was not read, every preview slot is busy"
    )


async def test_a_module_without_git_has_no_context7_json(catalog: FakeCatalog) -> None:
    added = await build(None, catalog).add_library(AddLibraryCommand(url=URL))

    assert (added.context7, added.context7_warning) == (None, None)


async def test_dropped_previous_versions_are_reported_as_notes(catalog: FakeCatalog) -> None:
    tree = tree_with(as_bytes({"previousVersions": [{"tag": "v1"}, {"tag": "-x"}]}))

    added = await build(tree, catalog).add_library(AddLibraryCommand(url=URL))

    assert added.context7 is not None
    assert [v.tag for v in added.context7.previous_versions] == ["v1"]
    assert len(added.context7.notes) == 1


async def test_the_preview_applies_and_returns_context7_json_without_paths(
    catalog: FakeCatalog,
) -> None:
    module = build(tree_with(as_bytes(FULL)), catalog)

    prefilled = await module.preview_repository(PreviewRepositoryCommand(url=URL))
    typed = await module.preview_repository(
        PreviewRepositoryCommand(url=URL, include_paths=["src/"])
    )

    assert prefilled.files == ["docs/a.md", "guides/b.md"]
    assert prefilled.include_paths == ["docs/", "guides/"]
    assert prefilled.context7 is not None
    assert prefilled.context7.project_title == "Acme Orders"
    assert typed.files == ["src/c.md"]
    assert typed.context7 == prefilled.context7
    assert catalog.added == []
