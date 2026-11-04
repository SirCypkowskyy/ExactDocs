"""``SyncLibraryUseCase``: which versions are re-imported, and what is recorded on failure."""

import asyncio
from dataclasses import dataclass, field

import pytest

from exactdocs.ingestion.adapters.driven.memory import (
    InMemoryCredentialVault,
    InMemoryJobRepository,
    InMemoryLibrarySources,
    NoIndex,
    NoRemovals,
)
from exactdocs.ingestion.dtos import EnqueueJobCommand, SyncLibraryCommand
from exactdocs.ingestion.errors import (
    CredentialsRequiredError,
    RepositoryUnreachableError,
    SyncFailedError,
    VersionImportingError,
)
from exactdocs.ingestion.models import (
    IMPORT_JOB,
    REFRESH_JOB,
    AccessToken,
    Credential,
    ImportedRef,
    ImportSource,
    Job,
    JobState,
    PathSelection,
    ProposedId,
    RefKind,
    RemoteRef,
    RemoteRefs,
    RepositoryHost,
    RepositoryUrl,
    SyncStatus,
)
from exactdocs.ingestion.module import IngestionModule
from exactdocs_kernel import NotFoundError

LIBRARY = "/acme/docs"
OLD, NEW, NEWER, TAG = "a" * 40, "b" * 40, "d" * 40, "c" * 40
URL = RepositoryUrl(
    url="https://example.com/acme/docs",
    host_kind=RepositoryHost.GIT,
    library_id=ProposedId(LIBRARY),
)
SOURCE = ImportSource(url=URL, selection=PathSelection.of([]), tag_rules=())


@dataclass
class Remote:
    heads: dict[str, str] = field(default_factory=dict)
    error: Exception | None = None
    slow: bool = False
    credentials: list[Credential | None] = field(default_factory=list)

    async def host_key_fingerprint(self, repository: RepositoryUrl) -> str | None:
        del repository

    async def list_refs(
        self, repository: RepositoryUrl, *patterns: str, credential: Credential | None = None
    ) -> RemoteRefs:
        del repository, patterns
        self.credentials.append(credential)
        if self.slow:
            await asyncio.sleep(0)  # a network round trip: other requests run meanwhile
        if self.error:
            raise self.error
        return RemoteRefs(
            default_branch="main",
            refs=tuple(RemoteRef(name=f"refs/heads/{n}", sha=s) for n, s in self.heads.items()),
        )


def branch(ref: str, sha: str = OLD) -> ImportedRef:
    return ImportedRef(ref=ref, kind=RefKind.BRANCH, commit_sha=sha)


async def _noop(job: object, progress: object, /) -> None: ...


@pytest.fixture
def remote() -> Remote:
    return Remote(heads={"main": OLD, "next": OLD})


@pytest.fixture
def versions() -> list[ImportedRef]:
    return [branch("main"), branch("next")]


def make_module(
    remote: Remote,
    versions: list[ImportedRef],
    jobs: InMemoryJobRepository,
    clock,
    vault: InMemoryCredentialVault | None = None,
) -> IngestionModule:
    return IngestionModule.build(
        jobs=jobs,
        clock=clock,
        remote=remote,
        library_ids=None,  # ty: ignore[invalid-argument-type]
        libraries=None,  # ty: ignore[invalid-argument-type]
        sources=InMemoryLibrarySources({LIBRARY: SOURCE}, {LIBRARY: versions}),
        removals=NoRemovals(),
        index=NoIndex(),
        vault=vault,
        handlers={IMPORT_JOB: _noop, REFRESH_JOB: _noop},
    )


@pytest.fixture
def module(
    remote: Remote, versions: list[ImportedRef], jobs: InMemoryJobRepository, clock
) -> IngestionModule:
    return make_module(remote, versions, jobs, clock)


SYNC = SyncLibraryCommand(library=LIBRARY)


def import_of(ref: str, sha: str = OLD) -> EnqueueJobCommand:
    return EnqueueJobCommand(
        kind=IMPORT_JOB, library=LIBRARY, version=ref, commit_sha=sha, ref_kind=RefKind.BRANCH
    )


async def test_a_moved_branch_queues_an_import_pinned_to_its_new_tip(
    module: IngestionModule, remote: Remote, jobs: InMemoryJobRepository
) -> None:
    remote.heads["next"] = NEW

    result = await module.sync_library(SYNC)

    by_ref = {v.ref: v for v in result.versions}
    assert by_ref["main"].status is SyncStatus.UP_TO_DATE
    assert by_ref["main"].job_id is None
    moved = by_ref["next"]
    assert (moved.status, moved.previous_commit_sha, moved.commit_sha) == (
        SyncStatus.QUEUED,
        OLD,
        NEW,
    )
    (job,) = jobs.jobs.values()
    assert job.id == moved.job_id
    assert (job.kind, job.library, job.version, job.commit_sha, job.ref_kind, job.state) == (
        REFRESH_JOB,
        LIBRARY,
        "next",
        NEW,
        RefKind.BRANCH,
        JobState.QUEUED,
    )


async def test_nothing_is_queued_when_no_branch_moved(
    module: IngestionModule, jobs: InMemoryJobRepository
) -> None:
    result = await module.sync_library(SYNC)

    assert {v.status for v in result.versions} == {SyncStatus.UP_TO_DATE}
    assert not jobs.jobs


async def test_tags_and_commits_are_pinned_and_never_ask_the_remote(
    module: IngestionModule,
    remote: Remote,
    versions: list[ImportedRef],
    jobs: InMemoryJobRepository,
) -> None:
    versions[:] = [
        ImportedRef(ref="v1", kind=RefKind.TAG, commit_sha=TAG),
        ImportedRef(ref=OLD, kind=RefKind.COMMIT, commit_sha=OLD),
    ]
    remote.error = RepositoryUnreachableError("down")  # would fail if the remote were asked

    result = await module.sync_library(SYNC)

    assert [v.status for v in result.versions] == [SyncStatus.PINNED, SyncStatus.PINNED]
    assert not jobs.jobs


async def test_a_busy_branch_is_reported_and_the_others_still_sync(
    module: IngestionModule, remote: Remote, jobs: InMemoryJobRepository
) -> None:
    busy = await module.enqueue_job(import_of("next"))
    remote.heads |= {"main": NEW, "next": NEW}

    result = await module.sync_library(SYNC)

    by_ref = {v.ref: v for v in result.versions}
    assert (by_ref["next"].status, by_ref["next"].job_id) == (SyncStatus.IMPORTING, busy.id)
    assert by_ref["main"].status is SyncStatus.QUEUED
    assert len(jobs.jobs) == 2


async def test_it_is_a_conflict_only_when_a_busy_branch_left_nothing_queued(
    module: IngestionModule, remote: Remote, jobs: InMemoryJobRepository
) -> None:
    await module.enqueue_job(import_of("next"))
    remote.heads["next"] = NEW  # main did not move, next is busy: nothing could be queued

    with pytest.raises(VersionImportingError) as raised:
        await module.sync_library(SYNC)

    assert raised.value.ref == "next"
    assert len(jobs.jobs) == 1


async def test_two_simultaneous_syncs_queue_one_import(
    module: IngestionModule, remote: Remote, jobs: InMemoryJobRepository
) -> None:
    remote.heads["next"] = NEW
    remote.slow = True  # both read the busy list before either has queued

    first, second = await asyncio.gather(
        module.sync_library(SYNC), module.sync_library(SYNC), return_exceptions=True
    )

    assert [type(r) for r in (first, second)].count(VersionImportingError) == 1
    assert len(jobs.jobs) == 1


async def test_an_unreachable_remote_fails_a_job_per_branch_and_names_them(
    module: IngestionModule, remote: Remote, jobs: InMemoryJobRepository
) -> None:
    remote.error = RepositoryUnreachableError("connection refused")

    with pytest.raises(SyncFailedError) as raised:
        await module.sync_library(SYNC)

    assert raised.value.code == RepositoryUnreachableError.code
    assert sorted(j.version or "" for j in jobs.jobs.values()) == ["main", "next"]
    assert {j.state for j in jobs.jobs.values()} == {JobState.FAILED}
    assert all("connection refused" in (j.error or "") for j in jobs.jobs.values())
    assert sorted(raised.value.job_ids) == sorted(jobs.jobs)
    assert all(job_id in str(raised.value) for job_id in jobs.jobs)


async def test_a_dead_remote_is_recorded_once_per_reason(
    module: IngestionModule, remote: Remote, jobs: InMemoryJobRepository
) -> None:
    remote.error = RepositoryUnreachableError("connection refused")
    for _ in range(3):
        with pytest.raises(SyncFailedError):
            await module.sync_library(SYNC)

    assert len(jobs.jobs) == 2


async def test_a_recovered_remote_clears_the_failure_with_a_succeeded_job(
    module: IngestionModule, remote: Remote, jobs: InMemoryJobRepository
) -> None:
    remote.error = RepositoryUnreachableError("connection refused")
    with pytest.raises(SyncFailedError):
        await module.sync_library(SYNC)
    remote.error = None

    result = await module.sync_library(SYNC)
    again = await module.sync_library(SYNC)

    assert {v.status for v in result.versions} == {SyncStatus.UP_TO_DATE}
    newest = {j.version: j for j in sorted(jobs.jobs.values(), key=lambda j: j.id)}
    assert {j.state for j in newest.values()} == {JobState.SUCCEEDED}
    assert len(jobs.jobs) == 4  # two failures, two no-ops; the third sync adds nothing
    assert all(v.job_id is None for v in again.versions)


async def test_a_branch_gone_upstream_fails_its_job_and_the_others_still_sync(
    module: IngestionModule, remote: Remote, jobs: InMemoryJobRepository
) -> None:
    del remote.heads["next"]
    remote.heads["main"] = NEW

    result = await module.sync_library(SYNC)

    by_ref = {v.ref: v for v in result.versions}
    assert by_ref["main"].status is SyncStatus.QUEUED
    assert by_ref["next"].status is SyncStatus.FAILED
    failed = jobs.jobs[by_ref["next"].job_id]  # ty: ignore[invalid-argument-type]
    assert (failed.state, failed.error) == (JobState.FAILED, "the branch no longer exists")


class FailsFor(InMemoryJobRepository):
    """Stores nothing for one version: a database error."""

    async def add(self, job: Job) -> None:
        if job.version == "next":
            msg = "database is locked"
            raise OSError(msg)
        await super().add(job)


async def test_a_failing_enqueue_is_one_failed_version_not_a_lost_response(
    remote: Remote,
    versions: list[ImportedRef],
    clock,
) -> None:
    jobs = FailsFor()
    module = make_module(remote, versions, jobs, clock)
    remote.heads |= {"main": NEW, "next": NEW}

    result = await module.sync_library(SYNC)

    by_ref = {v.ref: v for v in result.versions}
    assert by_ref["main"].status is SyncStatus.QUEUED
    assert (by_ref["next"].status, by_ref["next"].job_id) == (SyncStatus.FAILED, None)
    assert len(jobs.jobs) == 1


async def test_an_unknown_library_is_not_found(module: IngestionModule) -> None:
    with pytest.raises(NotFoundError):
        await module.sync_library(SyncLibraryCommand(library="/no/such"))


async def test_the_repository_refuses_a_second_unfinished_import_of_a_ref(
    module: IngestionModule,
) -> None:
    await module.enqueue_job(import_of("next"))

    with pytest.raises(VersionImportingError):
        await module.enqueue_job(import_of("next", NEW))
    await module.enqueue_job(import_of("main"))  # another ref is fine


async def test_a_private_librarys_sync_reads_the_remote_with_its_stored_credential(
    remote: Remote, versions: list[ImportedRef], jobs: InMemoryJobRepository, clock
) -> None:
    token = AccessToken(token="ghp_s3cretvalue")
    vault = InMemoryCredentialVault({LIBRARY: token})
    module = make_module(remote, versions, jobs, clock, vault)
    remote.heads["next"] = NEW

    result = await module.sync_library(SYNC)

    assert remote.credentials == [token]
    assert {v.ref: v.status for v in result.versions}["next"] is SyncStatus.QUEUED


async def test_a_public_librarys_sync_sends_no_credential(
    module: IngestionModule, remote: Remote
) -> None:
    await module.sync_library(SYNC)

    assert remote.credentials == [None]


async def test_an_unreadable_credential_is_recorded_on_each_branch_and_nothing_is_fetched(
    remote: Remote, versions: list[ImportedRef], jobs: InMemoryJobRepository, clock
) -> None:
    class Unreadable(InMemoryCredentialVault):
        async def load(self, library: str, scope: str) -> Credential | None:
            del library, scope
            raise CredentialsRequiredError

    module = make_module(remote, versions, jobs, clock, Unreadable())

    with pytest.raises(SyncFailedError) as raised:
        await module.sync_library(SYNC)

    assert raised.value.code == "credentials_required"
    assert remote.credentials == []  # the remote was never asked
    assert {j.state for j in jobs.jobs.values()} == {JobState.FAILED}
    assert sorted(j.version or "" for j in jobs.jobs.values()) == ["main", "next"]


async def test_a_credential_stored_for_another_host_is_not_used_by_a_sync(
    remote: Remote, versions: list[ImportedRef], jobs: InMemoryJobRepository, clock
) -> None:
    vault = InMemoryCredentialVault()
    await vault.save(LIBRARY, "https://elsewhere.example.com", AccessToken(token="t0ken"))
    module = make_module(remote, versions, jobs, clock, vault)

    with pytest.raises(SyncFailedError) as raised:
        await module.sync_library(SYNC)

    assert raised.value.code == "credentials_required"
    assert remote.credentials == []
