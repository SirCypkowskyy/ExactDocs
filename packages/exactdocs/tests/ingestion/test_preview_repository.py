from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from exactdocs.ingestion.adapters.driven.memory import InMemoryJobRepository, NoIndex, NoRemovals
from exactdocs.ingestion.dtos import PreviewRepositoryCommand
from exactdocs.ingestion.models import (
    Credential,
    FetchedFile,
    RemoteRef,
    RemoteRefs,
    RepositoryUrl,
)
from exactdocs.ingestion.module import IngestionModule
from exactdocs_kernel import SystemClock

TIP = "a" * 40
PATHS = ["README.md", "docs/b.md", "docs/a.MD", "docs/img.png", "docs/x/c.mdx", "src/d.md"]


@dataclass
class FakeRemote:
    async def host_key_fingerprint(self, repository: RepositoryUrl) -> str | None:
        del repository

    async def list_refs(
        self, repository: RepositoryUrl, *patterns: str, credential: Credential | None = None
    ) -> RemoteRefs:
        del repository, patterns, credential
        return RemoteRefs(
            default_branch="main",
            refs=(
                RemoteRef(name="refs/heads/main", sha=TIP),
                RemoteRef(name="refs/tags/v1", sha="b" * 40),
            ),
        )


@dataclass
class FakeTree:
    paths: list[str] = field(default_factory=lambda: list(PATHS))
    calls: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)

    async def list_files(
        self,
        repository: RepositoryUrl,
        commit_sha: str,
        *,
        refs: Sequence[str] = (),
        credential: Credential | None = None,
    ) -> list[str]:
        del repository, credential
        self.calls.append((commit_sha, tuple(refs)))
        return self.paths

    async def read_file(self, repository: RepositoryUrl, commit_sha: str, path: str, **_: object):
        del repository, commit_sha, path
        return FetchedFile()  # no context7.json


class _Libraries:
    async def add(self, library: object) -> str:
        del library
        raise AssertionError

    async def discard(self, library_id: str) -> None:
        del library_id
        raise AssertionError


class _Ids:
    async def is_taken(self, library_id: str) -> bool:
        del library_id
        raise AssertionError  # a preview ignores whether the ID is taken


def build(tree: FakeTree) -> IngestionModule:
    return IngestionModule.build(
        jobs=InMemoryJobRepository(),
        clock=SystemClock(),
        remote=FakeRemote(),
        tree=tree,
        library_ids=_Ids(),
        libraries=_Libraries(),
        removals=NoRemovals(),
        index=NoIndex(),
    )


URL = "https://github.com/acme/orders"


async def test_the_selection_decides_and_excludes_win() -> None:
    tree = FakeTree()

    preview = await build(tree).preview_repository(
        PreviewRepositoryCommand(url=URL, include_paths=["docs/**"], exclude_paths=["**/b.md"])
    )

    assert preview.files == ["docs/a.MD", "docs/x/c.mdx"]
    assert (preview.total, preview.truncated) == (2, False)
    assert (preview.ref, preview.ref_kind.value, preview.commit_sha) == ("main", "branch", TIP)
    assert tree.calls == [(TIP, ("refs/heads/main",))]


async def test_no_pattern_means_every_article() -> None:
    preview = await build(FakeTree()).preview_repository(PreviewRepositoryCommand(url=URL))

    assert preview.files == ["README.md", "docs/a.MD", "docs/b.md", "docs/x/c.mdx", "src/d.md"]


async def test_a_cap_keeps_the_first_files_and_the_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("exactdocs.ingestion.use_cases.MAX_PREVIEW_FILES", 2)

    preview = await build(FakeTree()).preview_repository(PreviewRepositoryCommand(url=URL))

    assert (preview.files, preview.total, preview.truncated) == (
        ["README.md", "docs/a.MD"],
        5,
        True,
    )


async def test_hostile_path_names_are_returned_as_data() -> None:
    names = [
        "<script>alert(1)</script>.md",
        "a\nb.md",
        "x\x00y.md",
        chr(0x202E) + "gnp.md",
        "[l](javascript:x).md",
    ]

    preview = await build(FakeTree(names)).preview_repository(PreviewRepositoryCommand(url=URL))

    assert sorted(preview.files) == sorted(names)
