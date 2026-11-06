from dataclasses import dataclass, field

import pytest
from pydantic import SecretStr

from exactdocs.ingestion.adapters.driven.memory import InMemoryJobRepository, NoIndex, NoRemovals
from exactdocs.ingestion.dtos import AccessTokenIn, CheckRepositoryCommand, ListRepositoryRefsQuery
from exactdocs.ingestion.errors import (
    InvalidCredentialError,
    InvalidRepositoryUrlError,
    LibraryIdTakenError,
    RepositoryUnreachableError,
)
from exactdocs.ingestion.models import (
    AccessToken,
    Credential,
    RemoteRef,
    RemoteRefs,
    RepositoryHost,
    RepositoryUrl,
)
from exactdocs.ingestion.module import IngestionModule
from exactdocs.ingestion.ports import GitRemote
from exactdocs_kernel import SystemClock


@dataclass
class FakeRemote:
    refs: RemoteRefs | Exception = field(default_factory=lambda: RemoteRefs(default_branch="main"))
    asked: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    credentials: list[Credential | None] = field(default_factory=list)

    async def host_key_fingerprint(self, repository: RepositoryUrl) -> str | None:
        del repository
        return None

    async def list_refs(
        self, repository: RepositoryUrl, *patterns: str, credential: Credential | None = None
    ) -> RemoteRefs:
        self.credentials.append(credential)
        self.asked.append((repository.url, patterns))
        if isinstance(self.refs, Exception):
            raise self.refs
        return self.refs


@dataclass(frozen=True)
class FakeLibraryIds:
    taken: frozenset[str] = frozenset()

    async def is_taken(self, library_id: str) -> bool:
        return library_id in self.taken


class _NoLibraries:
    async def add(self, library: object) -> str:
        raise NotImplementedError

    async def discard(self, library_id: str) -> None:
        raise NotImplementedError


def build(remote: GitRemote, taken: frozenset[str] = frozenset()) -> IngestionModule:
    return IngestionModule.build(
        jobs=InMemoryJobRepository(),
        clock=SystemClock(),
        remote=remote,
        library_ids=FakeLibraryIds(taken),
        libraries=_NoLibraries(),
        removals=NoRemovals(),
        index=NoIndex(),
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


TOKEN = AccessTokenIn(kind="token", token=SecretStr("glpat-secret"))


async def test_the_refs_of_a_private_repository_are_listed_with_the_credential_sent() -> None:
    remote = FakeRemote(
        RemoteRefs(default_branch="main", refs=(RemoteRef(name="refs/tags/v1", sha="a" * 40),))
    )

    refs = await build(remote).list_repository_refs(
        ListRepositoryRefsQuery(url="https://git.example.com/acme/private", credential=TOKEN)
    )

    assert [t.name for t in refs.tags] == ["v1"]
    assert remote.credentials == [AccessToken(token="glpat-secret")]


async def test_refs_without_a_credential_ask_the_remote_without_one() -> None:
    remote = FakeRemote()

    await build(remote).list_repository_refs(
        ListRepositoryRefsQuery(url="https://git.example.com/acme/x")
    )

    assert remote.credentials == [None]


async def test_a_token_for_an_ssh_url_is_refused_before_any_network_traffic() -> None:
    remote = FakeRemote()

    with pytest.raises(InvalidCredentialError):
        await build(remote).list_repository_refs(
            ListRepositoryRefsQuery(url="git@git.example.com:acme/x.git", credential=TOKEN)
        )

    assert remote.asked == []
