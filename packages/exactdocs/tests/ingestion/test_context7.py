"""A repository's ``context7.json`` (LIB-06): parsing, and how adding or previewing uses it."""

import json
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from exactdocs.ingestion.adapters.driven.memory import InMemoryJobRepository, NoIndex, NoRemovals
from exactdocs.ingestion.dtos import AddLibraryCommand, PreviewRepositoryCommand
from exactdocs.ingestion.errors import InvalidContext7Error, RepositoryUnreachableError
from exactdocs.ingestion.models import (
    CONTEXT7_MAX_BYTES,
    IMPORT_JOB,
    MAX_CONTEXT7_RULES,
    Context7Config,
    Credential,
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
        (as_bytes({"rules": ["r"] * (MAX_CONTEXT7_RULES + 1)}), "rules: at most"),
        (as_bytes({"rules": ["r" * 501]}), "rules: at most"),
        (as_bytes({"folders": ["../secrets"]}), "folders or excludes"),
        (as_bytes({"previousVersions": ["v1"]}), "previousVersions must be"),
        (as_bytes({"previousVersions": [{"title": "x"}]}), "previousVersions must be"),
        (as_bytes({"previousVersions": [{"tag": "v 1"}]}), "a tag is one word"),
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
class FakeGateway:
    """Plays ``GitGateway.fetch_files``: the repository's root holds ``files``."""

    tmp: Path
    files: dict[str, bytes] = field(default_factory=dict)
    error: Exception | None = None
    asked: list[list[str]] = field(default_factory=list)

    def fetch(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError  # adding or previewing never checks out the docs

    @asynccontextmanager
    async def fetch_files(
        self,
        repository: RepositoryUrl,
        commit_sha: str,
        paths: Sequence[str],
        *,
        max_bytes: int,
        refs: Sequence[str] = (),
        credential: Credential | None = None,
    ) -> AsyncGenerator[Path]:
        del repository, max_bytes, refs, credential
        assert commit_sha == TIP
        self.asked.append(list(paths))
        if self.error:
            raise self.error
        folder = self.tmp / f"fetch-{len(self.asked)}"
        folder.mkdir()
        for name in paths:
            if name in self.files:
                (folder / name).write_bytes(self.files[name])
        yield folder


@dataclass
class FakeTree:
    async def list_files(self, repository: RepositoryUrl, commit_sha: str, **_: object) -> list:
        del repository, commit_sha
        return ["README.md", "docs/a.md", "docs/archive/old.md", "guides/b.md", "src/c.md"]


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


def build(gateway: FakeGateway | None, catalog: FakeCatalog) -> IngestionModule:
    handlers: dict = {IMPORT_JOB: _run}
    return IngestionModule.build(
        jobs=InMemoryJobRepository(),
        clock=SystemClock(),
        remote=FakeRemote(),
        tree=FakeTree(),
        gateway=gateway,  # ty: ignore[invalid-argument-type]
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
    tmp_path: Path, catalog: FakeCatalog
) -> None:
    gateway = FakeGateway(tmp_path, {"context7.json": as_bytes(FULL)})

    added = await build(gateway, catalog).add_library(AddLibraryCommand(url=URL))

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
    assert added.context7_warning is None
    assert gateway.asked == [["context7.json"]]


@pytest.mark.parametrize(
    "command",
    [
        AddLibraryCommand(url=URL, include_paths=["src/"]),
        AddLibraryCommand(url=URL, exclude_paths=["src/"]),
    ],
    ids=["include", "exclude"],
)
async def test_paths_a_user_sends_win_over_context7_json(
    tmp_path: Path, catalog: FakeCatalog, command: AddLibraryCommand
) -> None:
    gateway = FakeGateway(tmp_path, {"context7.json": as_bytes(FULL)})

    added = await build(gateway, catalog).add_library(command)

    (library,) = catalog.added
    assert library.selection == PathSelection.of(command.include_paths, command.exclude_paths)
    assert added.context7 is not None  # still reported, e.g. for its previous versions


@pytest.mark.parametrize(
    ("files", "error", "warning"),
    [
        ({}, None, None),
        ({"context7.json": b"{"}, None, "context7.json is ignored: it is not valid JSON"),
        ({}, RepositoryUnreachableError("gone"), "context7.json is ignored: it could not be"),
    ],
    ids=["absent", "invalid", "unfetchable"],
)
async def test_a_missing_or_unusable_file_adds_the_library_as_if_there_were_none(
    tmp_path: Path,
    catalog: FakeCatalog,
    files: dict[str, bytes],
    error: Exception | None,
    warning: str | None,
) -> None:
    gateway = FakeGateway(tmp_path, files, error)

    added = await build(gateway, catalog).add_library(AddLibraryCommand(url=URL))

    (library,) = catalog.added
    assert library.selection == PathSelection.of()
    assert added.context7 is None
    assert (added.context7_warning or "").startswith(warning or "")
    assert (added.context7_warning is None) is (warning is None)


async def test_a_module_without_git_has_no_context7_json(catalog: FakeCatalog) -> None:
    added = await build(None, catalog).add_library(AddLibraryCommand(url=URL))

    assert (added.context7, added.context7_warning) == (None, None)


async def test_the_preview_applies_and_returns_context7_json_without_paths(
    tmp_path: Path, catalog: FakeCatalog
) -> None:
    gateway = FakeGateway(tmp_path, {"context7.json": as_bytes(FULL)})
    module = build(gateway, catalog)

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
