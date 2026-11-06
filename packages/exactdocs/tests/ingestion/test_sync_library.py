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
from exactdocs.ingestion.dtos import EnqueueJobCommand, ReimportVersionCommand, SyncLibraryCommand
from exactdocs.ingestion.errors import (
    CredentialsRequiredError,
    HostKeyChangedError,
    NotAGitRepositoryError,
    NotATagError,
    RefDeletedError,
    RepositoryAuthRequiredError,
    RepositoryUnreachableError,
    SyncFailedError,
    TagNotMovedError,
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
    JobId,
    JobState,
    PathSelection,
    ProposedId,
    RefKind,
    RemoteRef,
    RemoteRefs,
    RepositoryHost,
    RepositoryUrl,
    SyncErrorCode,
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
    tags: dict[str, str] = field(default_factory=dict)
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
            refs=(
                *(RemoteRef(name=f"refs/heads/{n}", sha=s) for n, s in self.heads.items()),
                *(RemoteRef(name=f"refs/tags/{n}", sha=s) for n, s in self.tags.items()),
            ),
        )


def branch(ref: str, sha: str = OLD) -> ImportedRef:
    return ImportedRef(ref=ref, kind=RefKind.BRANCH, commit_sha=sha)


def tag(ref: str, sha: str = TAG) -> ImportedRef:
    return ImportedRef(ref=ref, kind=RefKind.TAG, commit_sha=sha)


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
        sources=InMemoryLibrarySources(sources={LIBRARY: SOURCE}, versions={LIBRARY: versions}),
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


async def test_commits_are_pinned_and_never_ask_the_remote(
    module: IngestionModule,
    remote: Remote,
    versions: list[ImportedRef],
    jobs: InMemoryJobRepository,
) -> None:
    versions[:] = [ImportedRef(ref=OLD, kind=RefKind.COMMIT, commit_sha=OLD)]
    remote.error = RepositoryUnreachableError("down")  # would fail if the remote were asked

    result = await module.sync_library(SYNC)

    assert [v.status for v in result.versions] == [SyncStatus.PINNED]
    assert remote.credentials == []
    assert not jobs.jobs


async def test_a_tag_that_still_names_its_commit_is_pinned(
    module: IngestionModule,
    remote: Remote,
    versions: list[ImportedRef],
    jobs: InMemoryJobRepository,
) -> None:
    versions[:] = [tag("v1")]
    remote.tags["v1"] = TAG

    result = await module.sync_library(SYNC)

    assert [(v.status, v.error_code, v.job_id) for v in result.versions] == [
        (SyncStatus.PINNED, None, None)
    ]
    assert not jobs.jobs


async def test_an_annotated_tag_is_compared_by_the_commit_it_peels_to(
    module: IngestionModule, remote: Remote, versions: list[ImportedRef]
) -> None:
    versions[:] = [tag("v1")]
    remote.tags |= {"v1": NEWER, "v1^{}": TAG}  # NEWER is the tag object, TAG its commit

    result = await module.sync_library(SYNC)

    assert [v.status for v in result.versions] == [SyncStatus.PINNED]


async def test_a_moved_tag_is_reported_and_never_re_imported(
    module: IngestionModule,
    remote: Remote,
    versions: list[ImportedRef],
    jobs: InMemoryJobRepository,
) -> None:
    versions.append(tag("v1"))
    remote.tags["v1"] = NEW

    result = await module.sync_library(SYNC)

    moved = {v.ref: v for v in result.versions}["v1"]
    assert (moved.status, moved.error_code, moved.commit_sha) == (
        SyncStatus.FAILED,
        SyncErrorCode.TAG_MOVED,
        TAG,  # still what it serves
    )
    assert moved.error
    assert NEW in moved.error
    assert TAG in moved.error
    (job,) = jobs.jobs.values()  # a record of the failure, no import
    assert (job.id, job.state, job.error_code, job.version) == (
        moved.job_id,
        JobState.FAILED,
        "tag_moved",
        "v1",
    )
    assert job.finished_at is not None


async def test_a_moved_tag_is_recorded_once_and_cleared_when_it_comes_back(
    module: IngestionModule,
    remote: Remote,
    versions: list[ImportedRef],
    jobs: InMemoryJobRepository,
) -> None:
    versions[:] = [tag("v1")]
    remote.tags["v1"] = NEW
    await module.sync_library(SYNC)
    await module.sync_library(SYNC)
    remote.tags["v1"] = TAG

    result = await module.sync_library(SYNC)

    assert [v.status for v in result.versions] == [SyncStatus.PINNED]
    states = [j.state for j in sorted(jobs.jobs.values(), key=lambda j: j.id)]
    assert states == [JobState.FAILED, JobState.SUCCEEDED]


@pytest.mark.parametrize("kind", ["branch", "tag"])
async def test_a_ref_deleted_upstream_is_ref_deleted(
    module: IngestionModule,
    versions: list[ImportedRef],
    jobs: InMemoryJobRepository,
    kind: str,
) -> None:
    versions[:] = [branch("gone") if kind == "branch" else tag("gone")]

    result = await module.sync_library(SYNC)

    (gone,) = result.versions
    assert (gone.status, gone.error_code) == (SyncStatus.FAILED, SyncErrorCode.REF_DELETED)
    assert gone.error == f"the {kind} 'gone' no longer exists in the repository"
    assert jobs.jobs[gone.job_id].error_code == "ref_deleted"  # ty: ignore[invalid-argument-type]


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

    assert raised.value.code == "repo_unreachable"
    assert raised.value.cause_code == RepositoryUnreachableError.code
    assert sorted(j.version or "" for j in jobs.jobs.values()) == ["main", "next"]
    assert {(j.state, j.error_code) for j in jobs.jobs.values()} == {
        (JobState.FAILED, "repo_unreachable")
    }
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
    assert (failed.state, failed.error_code) == (JobState.FAILED, SyncErrorCode.REF_DELETED)
    assert failed.error == "the branch 'next' no longer exists in the repository"


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
    vault = InMemoryCredentialVault(credentials={LIBRARY: token})
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

    assert (raised.value.code, raised.value.cause_code) == ("auth_failed", "credentials_required")
    assert remote.credentials == []  # the remote was never asked
    assert {(j.state, j.error_code) for j in jobs.jobs.values()} == {
        (JobState.FAILED, "auth_failed")
    }
    assert sorted(j.version or "" for j in jobs.jobs.values()) == ["main", "next"]


async def test_a_credential_stored_for_another_host_is_not_used_by_a_sync(
    remote: Remote, versions: list[ImportedRef], jobs: InMemoryJobRepository, clock
) -> None:
    vault = InMemoryCredentialVault()
    await vault.save(LIBRARY, "https://elsewhere.example.com", AccessToken(token="t0ken"))
    module = make_module(remote, versions, jobs, clock, vault)

    with pytest.raises(SyncFailedError) as raised:
        await module.sync_library(SYNC)

    assert raised.value.code == "auth_failed"
    assert remote.credentials == []


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (NotAGitRepositoryError(), "repo_unreachable"),  # deleted, or private without a login
        (RepositoryUnreachableError("connection refused"), "repo_unreachable"),
        (RepositoryAuthRequiredError(), "repo_unreachable"),  # no token sent: gone or private
        (HostKeyChangedError(), "host_key_changed"),  # not a credential problem: a warning
    ],
)
async def test_a_remote_that_cannot_be_read_says_why(
    module: IngestionModule,
    remote: Remote,
    versions: list[ImportedRef],
    jobs: InMemoryJobRepository,
    error: Exception,
    code: str,
) -> None:
    versions.append(tag("v1"))
    remote.error = error

    with pytest.raises(SyncFailedError) as raised:
        await module.sync_library(SYNC)

    assert raised.value.code == code
    assert sorted(j.version or "" for j in jobs.jobs.values()) == ["main", "next", "v1"]
    assert {j.error_code for j in jobs.jobs.values()} == {code}


async def test_an_auth_demand_with_a_stored_credential_is_an_auth_failure(
    remote: Remote, versions: list[ImportedRef], jobs: InMemoryJobRepository, clock
) -> None:
    vault = InMemoryCredentialVault(credentials={LIBRARY: AccessToken(token="ghp_revoked")})
    module = make_module(remote, versions, jobs, clock, vault)
    remote.error = RepositoryAuthRequiredError()  # an expired or revoked token

    with pytest.raises(SyncFailedError) as raised:
        await module.sync_library(SYNC)

    assert (raised.value.code, raised.value.cause_code) == (
        "auth_failed",
        RepositoryAuthRequiredError.code,
    )
    assert {j.error_code for j in jobs.jobs.values()} == {"auth_failed"}


async def test_an_auth_demand_without_a_credential_means_the_repository_is_gone_or_private(
    module: IngestionModule, remote: Remote, jobs: InMemoryJobRepository
) -> None:
    # GitHub answers a deleted repository with 401, not 404, so it does not reveal private ones.
    remote.error = RepositoryAuthRequiredError()

    with pytest.raises(SyncFailedError) as raised:
        await module.sync_library(SYNC)

    assert (raised.value.code, raised.value.cause_code) == (
        "repo_unreachable",
        NotAGitRepositoryError.code,
    )
    assert {j.error_code for j in jobs.jobs.values()} == {"repo_unreachable"}
    assert all("no git repository was found" in (j.error or "") for j in jobs.jobs.values())


def reimport(ref: str = "v1") -> ReimportVersionCommand:
    return ReimportVersionCommand(library=LIBRARY, ref=ref)


async def test_a_confirmed_moved_tag_is_queued_at_its_new_commit_and_its_error_clears(
    module: IngestionModule,
    remote: Remote,
    versions: list[ImportedRef],
    jobs: InMemoryJobRepository,
) -> None:
    versions[:] = [tag("v1")]
    remote.tags["v1"] = NEW
    await module.sync_library(SYNC)  # reported as tag_moved

    result = await module.reimport_version(reimport())

    assert (result.ref, result.ref_kind, result.previous_commit_sha, result.commit_sha) == (
        "v1",
        RefKind.TAG,
        TAG,
        NEW,
    )
    job = jobs.jobs[JobId(result.job_id)]
    assert (job.kind, job.state, job.version, job.commit_sha, job.ref_kind) == (
        REFRESH_JOB,  # replaces the version in place, never resurrects a removed one
        JobState.QUEUED,
        "v1",
        NEW,
        RefKind.TAG,
    )
    (latest,) = (await module.list_latest_jobs()).jobs
    assert (latest.id, latest.error_code) == (result.job_id, None)  # the error is not the state


async def test_a_tag_is_re_imported_by_its_remote_tip_not_by_a_sync_record(
    module: IngestionModule, remote: Remote, versions: list[ImportedRef]
) -> None:
    versions[:] = [tag("v1")]
    remote.tags["v1"] = NEW  # moved, but no sync reported it yet

    result = await module.reimport_version(reimport())

    assert result.commit_sha == NEW


async def test_a_tag_that_did_not_move_is_not_re_imported(
    module: IngestionModule,
    remote: Remote,
    versions: list[ImportedRef],
    jobs: InMemoryJobRepository,
) -> None:
    versions[:] = [tag("v1")]
    remote.tags["v1"] = TAG

    with pytest.raises(TagNotMovedError) as raised:
        await module.reimport_version(reimport())

    assert raised.value.code == "tag_not_moved"
    assert not jobs.jobs


async def test_a_moved_tag_that_moved_back_is_not_re_imported(
    module: IngestionModule,
    remote: Remote,
    versions: list[ImportedRef],
    jobs: InMemoryJobRepository,
) -> None:
    versions[:] = [tag("v1")]
    remote.tags["v1"] = NEW
    await module.sync_library(SYNC)
    remote.tags["v1"] = TAG  # the reported move is over by the time it is confirmed

    with pytest.raises(TagNotMovedError):
        await module.reimport_version(reimport())

    assert [j.state for j in jobs.jobs.values()] == [JobState.FAILED]


@pytest.mark.parametrize(("ref", "kind"), [("main", "branch"), (OLD, "commit")])
async def test_only_a_tag_version_is_re_imported(
    module: IngestionModule,
    remote: Remote,
    versions: list[ImportedRef],
    jobs: InMemoryJobRepository,
    ref: str,
    kind: str,
) -> None:
    versions.append(ImportedRef(ref=OLD, kind=RefKind.COMMIT, commit_sha=OLD))
    remote.heads["main"] = NEW

    with pytest.raises(NotATagError) as raised:
        await module.reimport_version(reimport(ref))

    assert raised.value.code == "not_a_tag"
    assert kind in str(raised.value)
    assert not jobs.jobs
    assert remote.credentials == []  # refused before the remote is asked


async def test_a_tag_gone_upstream_is_ref_deleted(
    module: IngestionModule, versions: list[ImportedRef], jobs: InMemoryJobRepository
) -> None:
    versions[:] = [tag("v1")]

    with pytest.raises(RefDeletedError) as raised:
        await module.reimport_version(reimport())

    assert raised.value.code == "ref_deleted"
    assert not jobs.jobs


async def test_a_tag_being_imported_is_not_queued_twice(
    module: IngestionModule,
    remote: Remote,
    versions: list[ImportedRef],
    jobs: InMemoryJobRepository,
) -> None:
    versions[:] = [tag("v1")]
    remote.tags["v1"] = NEW
    await module.reimport_version(reimport())

    with pytest.raises(VersionImportingError):
        await module.reimport_version(reimport())

    assert len(jobs.jobs) == 1


async def test_two_simultaneous_confirmations_queue_one_import(
    module: IngestionModule,
    remote: Remote,
    versions: list[ImportedRef],
    jobs: InMemoryJobRepository,
) -> None:
    versions[:] = [tag("v1")]
    remote.tags["v1"] = NEW
    remote.slow = True

    results = await asyncio.gather(
        module.reimport_version(reimport()),
        module.reimport_version(reimport()),
        return_exceptions=True,
    )

    assert sorted(type(r).__name__ for r in results) == [
        "ReimportedVersion",
        "VersionImportingError",
    ]
    assert len(jobs.jobs) == 1


@pytest.mark.parametrize("ref", ["v2", "V1"])
async def test_an_unknown_version_is_not_found(
    module: IngestionModule, versions: list[ImportedRef], ref: str
) -> None:
    versions[:] = [tag("v1")]

    with pytest.raises(NotFoundError):
        await module.reimport_version(reimport(ref))


async def test_an_unknown_library_is_not_found_for_a_re_import(module: IngestionModule) -> None:
    with pytest.raises(NotFoundError):
        await module.reimport_version(ReimportVersionCommand(library="/acme/nope", ref="v1"))


async def test_a_private_tag_is_checked_with_its_stored_credential(
    remote: Remote, versions: list[ImportedRef], jobs: InMemoryJobRepository, clock
) -> None:
    token = AccessToken(token="ghp_s3cretvalue")
    module = make_module(
        remote, versions, jobs, clock, InMemoryCredentialVault(credentials={LIBRARY: token})
    )
    versions[:] = [tag("v1")]
    remote.tags["v1"] = NEW

    await module.reimport_version(reimport())

    assert remote.credentials == [token]


async def test_a_login_prompt_without_a_credential_means_the_repository_is_gone(
    module: IngestionModule, remote: Remote, versions: list[ImportedRef]
) -> None:
    versions[:] = [tag("v1")]
    remote.error = RepositoryAuthRequiredError()

    with pytest.raises(NotAGitRepositoryError):
        await module.reimport_version(reimport())
