import pytest

from exactdocs.ingestion.adapters.driven.memory import InMemoryJobRepository, InMemoryLibrarySources
from exactdocs.ingestion.dtos import AddVersionCommand
from exactdocs.ingestion.errors import (
    AmbiguousRefError,
    CommitImportedError,
    UnknownRefError,
    VersionExistsError,
    VersionImportingError,
)
from exactdocs.ingestion.models import (
    IMPORT_JOB,
    ImportSource,
    JobId,
    PathSelection,
    RefKind,
    RemoteRef,
    RemoteRefs,
    RepositoryUrl,
    TagRule,
)
from exactdocs.ingestion.module import IngestionModule
from exactdocs_kernel import NotFoundError, SystemClock

MAIN, OLD, NEW = "a" * 40, "b" * 40, "c" * 40
REFS = RemoteRefs(
    default_branch="main",
    refs=(
        RemoteRef(name="refs/heads/main", sha=MAIN),
        RemoteRef(name="refs/tags/v1.3.0", sha=OLD),
        RemoteRef(name="refs/tags/v1.4.0", sha=NEW),
        RemoteRef(name="refs/heads/v1.4.0", sha=MAIN),
        RemoteRef(name="refs/heads/same", sha=NEW),
        RemoteRef(name="refs/tags/v2.0.0", sha="e" * 7 + "1" * 33),
        RemoteRef(name="refs/tags/v2.0.1", sha="e" * 7 + "2" * 33),
    ),
)
SOURCE = ImportSource(
    url=RepositoryUrl.parse("https://github.com/Acme/Orders"),
    selection=PathSelection(include=("docs/**",), exclude=("docs/archive/**",)),
    tag_rules=TagRule.many([("docs/api/**", "api")]),
)
EXISTING = {"v1.4.0": NEW}


class FakeRemote:
    async def list_refs(self, repository: RepositoryUrl, *patterns: str) -> RemoteRefs:
        del repository, patterns
        return REFS


async def _run(job: object, progress: object, /) -> None: ...


@pytest.fixture
def jobs() -> InMemoryJobRepository:
    return InMemoryJobRepository()


@pytest.fixture
def module(jobs: InMemoryJobRepository) -> IngestionModule:
    class _None:
        async def is_taken(self, library_id: str) -> bool:
            del library_id
            return False

        async def add(self, library: object) -> str:
            raise NotImplementedError

        async def discard(self, library_id: str) -> None:
            raise NotImplementedError

    return IngestionModule.build(
        jobs=jobs,
        clock=SystemClock(),
        remote=FakeRemote(),
        library_ids=_None(),
        libraries=_None(),
        sources=InMemoryLibrarySources({"/acme/orders": SOURCE}, {"/acme/orders": EXISTING}),
        handlers={IMPORT_JOB: _run},
    )


async def test_a_tag_is_pinned_and_its_import_queued(
    module: IngestionModule, jobs: InMemoryJobRepository
) -> None:
    added = await module.add_version(AddVersionCommand(library="/acme/orders", ref="v1.3.0"))

    assert (added.library_id, added.ref, added.ref_kind, added.commit_sha) == (
        "/acme/orders",
        "v1.3.0",
        "tag",
        OLD,
    )
    job = await jobs.get(JobId(added.job_id))
    assert job is not None
    assert (job.kind, job.library, job.version, job.commit_sha, job.ref_kind) == (
        IMPORT_JOB,
        "/acme/orders",
        "v1.3.0",
        OLD,
        RefKind.TAG,
    )


async def test_a_short_sha_becomes_the_full_one(module: IngestionModule) -> None:
    added = await module.add_version(AddVersionCommand(library="/acme/orders", ref=OLD[:9]))

    assert (added.ref, added.ref_kind) == (OLD, "commit")


async def test_a_ref_the_library_has_is_refused_and_queues_nothing(
    module: IngestionModule, jobs: InMemoryJobRepository
) -> None:
    with pytest.raises(VersionExistsError) as error:
        await module.add_version(AddVersionCommand(library="/acme/orders", ref="v1.4.0"))

    assert error.value.code == "version_exists"
    assert not await jobs.list_for_library("/acme/orders")


async def test_an_import_in_progress_for_the_ref_is_refused(
    module: IngestionModule, jobs: InMemoryJobRepository
) -> None:
    await module.add_version(AddVersionCommand(library="/acme/orders", ref="v1.3.0"))

    with pytest.raises(VersionImportingError) as error:
        await module.add_version(AddVersionCommand(library="/acme/orders", ref="v1.3.0"))

    assert error.value.code == "version_importing"
    assert len(await jobs.list_for_library("/acme/orders")) == 1


async def test_a_finished_import_does_not_block_the_ref(
    module: IngestionModule, jobs: InMemoryJobRepository
) -> None:
    first = await module.add_version(AddVersionCommand(library="/acme/orders", ref="v1.3.0"))
    job = await jobs.get(JobId(first.job_id))
    assert job is not None
    await jobs.save(job.failed("boom", job.created_at))

    again = await module.add_version(AddVersionCommand(library="/acme/orders", ref="v1.3.0"))

    assert again.job_id != first.job_id


async def test_a_sha_that_is_already_a_version_is_refused_naming_it(
    module: IngestionModule, jobs: InMemoryJobRepository
) -> None:
    with pytest.raises(CommitImportedError) as error:
        await module.add_version(AddVersionCommand(library="/acme/orders", ref=NEW[:9]))

    assert (error.value.code, error.value.ref) == ("commit_already_imported", "v1.4.0")
    assert not await jobs.list_for_library("/acme/orders")


async def test_a_branch_at_an_imported_commit_is_still_its_own_version(
    module: IngestionModule,
) -> None:
    added = await module.add_version(AddVersionCommand(library="/acme/orders", ref="same"))

    assert (added.ref, added.commit_sha) == ("same", NEW)


async def test_a_tag_that_shadows_a_branch_is_one_version(module: IngestionModule) -> None:
    # "v1.4.0" is both a tag and a branch (REFS); the tag wins and the library has it already
    with pytest.raises(VersionExistsError):
        await module.add_version(AddVersionCommand(library="/acme/orders", ref="v1.4.0"))


async def test_refs_are_case_sensitive(module: IngestionModule) -> None:
    with pytest.raises(UnknownRefError):
        await module.add_version(AddVersionCommand(library="/acme/orders", ref="V1.3.0"))


async def test_an_unknown_ref_queues_nothing(
    module: IngestionModule, jobs: InMemoryJobRepository
) -> None:
    with pytest.raises(UnknownRefError):
        await module.add_version(AddVersionCommand(library="/acme/orders", ref="v9.9.9"))

    assert not await jobs.list_for_library("/acme/orders")


async def test_an_ambiguous_short_sha_is_refused(module: IngestionModule) -> None:
    with pytest.raises(AmbiguousRefError):
        await module.add_version(AddVersionCommand(library="/acme/orders", ref="e" * 7))


async def test_an_unknown_library_is_not_found(module: IngestionModule) -> None:
    with pytest.raises(NotFoundError):
        await module.add_version(AddVersionCommand(library="/acme/nope", ref="v1.3.0"))
