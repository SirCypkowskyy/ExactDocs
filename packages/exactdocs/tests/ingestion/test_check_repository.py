from dataclasses import dataclass, field

import pytest

from exactdocs.ingestion.adapters.driven.memory import InMemoryJobRepository
from exactdocs.ingestion.dtos import CheckRepositoryCommand
from exactdocs.ingestion.errors import (
    InvalidRepositoryUrlError,
    LibraryIdTakenError,
    RepositoryUnreachableError,
)
from exactdocs.ingestion.models import RemoteRef, RemoteRefs, RepositoryHost, RepositoryUrl
from exactdocs.ingestion.module import IngestionModule
from exactdocs.ingestion.ports import GitRemote
from exactdocs_kernel import SystemClock


@dataclass
class FakeRemote:
    refs: RemoteRefs | Exception = field(default_factory=lambda: RemoteRefs(default_branch="main"))
    asked: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)

    async def list_refs(self, repository: RepositoryUrl, *patterns: str) -> RemoteRefs:
        self.asked.append((repository.url, patterns))
        if isinstance(self.refs, Exception):
            raise self.refs
        return self.refs


@dataclass(frozen=True)
class FakeLibraryIds:
    taken: frozenset[str] = frozenset()

    async def is_taken(self, library_id: str) -> bool:
        return library_id in self.taken


def build(remote: GitRemote, taken: frozenset[str] = frozenset()) -> IngestionModule:
    return IngestionModule.build(
        jobs=InMemoryJobRepository(),
        clock=SystemClock(),
        remote=remote,
        library_ids=FakeLibraryIds(taken),
    )


async def test_a_reachable_repository_is_accepted_with_a_proposed_id() -> None:
    remote = FakeRemote(
        RemoteRefs(default_branch="trunk", refs=(RemoteRef(name="HEAD", sha="a" * 40),))
    )

    checked = await build(remote).check_repository(
        CheckRepositoryCommand(url="https://github.com/Acme/Payments")
    )

    assert (checked.host, checked.library_id, checked.default_branch) == (
        RepositoryHost.GITHUB,
        "/acme/payments",
        "trunk",
    )
    assert remote.asked == [("https://github.com/Acme/Payments", ("HEAD",))]


async def test_an_empty_repository_is_accepted_without_a_default_branch() -> None:
    checked = await build(FakeRemote(RemoteRefs(default_branch=None))).check_repository(
        CheckRepositoryCommand(url="https://git.example.com/acme/empty.git")
    )

    assert checked.default_branch is None


async def test_a_taken_id_is_refused_before_any_network_traffic() -> None:
    remote = FakeRemote()
    module = build(remote, frozenset({"/acme/payments"}))

    with pytest.raises(LibraryIdTakenError, match="choose another library ID") as error:
        await module.check_repository(
            CheckRepositoryCommand(url="https://bitbucket.org/acme/payments")
        )

    assert error.value.code == "library_id_taken"
    assert remote.asked == []


async def test_an_unusable_url_never_reaches_git() -> None:
    remote = FakeRemote()

    with pytest.raises(InvalidRepositoryUrlError):
        await build(remote).check_repository(CheckRepositoryCommand(url="ext::sh -c id"))

    assert remote.asked == []


async def test_remote_failures_reach_the_caller() -> None:
    module = build(FakeRemote(RepositoryUnreachableError("no answer within 15 seconds")))

    with pytest.raises(RepositoryUnreachableError):
        await module.check_repository(CheckRepositoryCommand(url="https://git.example.com/acme/x"))
