from dataclasses import dataclass, field

import pytest

from exactdocs.ingestion.adapters.driven.memory import InMemoryJobRepository
from exactdocs.ingestion.dtos import AddLibraryCommand, ListRepositoryRefsQuery
from exactdocs.ingestion.errors import (
    InvalidPathPatternError,
    InvalidRepositoryUrlError,
    LibraryIdTakenError,
    UnknownJobKindError,
    UnknownRefError,
)
from exactdocs.ingestion.models import (
    IMPORT_JOB,
    JobId,
    NewLibrary,
    PathSelection,
    RemoteRef,
    RemoteRefs,
    RepositoryHost,
    RepositoryUrl,
)
from exactdocs.ingestion.module import IngestionModule
from exactdocs.ingestion.use_cases import MAX_LISTED_REFS
from exactdocs_kernel import SystemClock

HEAD, TAG = "a" * 40, "b" * 40
REFS = RemoteRefs(
    default_branch="main",
    refs=(
        RemoteRef(name="refs/heads/main", sha=HEAD),
        RemoteRef(name="refs/tags/v1.0.0", sha=TAG),
    ),
)
URL = "https://github.com/Acme/Orders"


@dataclass
class FakeRemote:
    refs: RemoteRefs = REFS
    asked: int = 0

    async def list_refs(self, repository: RepositoryUrl, *patterns: str) -> RemoteRefs:
        del repository, patterns
        self.asked += 1
        return self.refs


@dataclass
class FakeCatalog:
    taken: set[str] = field(default_factory=set)
    added: list[NewLibrary] = field(default_factory=list)
    discarded: list[str] = field(default_factory=list)

    async def is_taken(self, library_id: str) -> bool:
        return library_id in self.taken

    async def add(self, library: NewLibrary) -> str:
        self.added.append(library)
        return library.library_id

    async def discard(self, library_id: str) -> None:
        self.discarded.append(library_id)


async def _run(job: object, progress: object, /) -> None: ...


@pytest.fixture
def remote() -> FakeRemote:
    return FakeRemote()


@pytest.fixture
def catalog() -> FakeCatalog:
    return FakeCatalog()


@pytest.fixture
def jobs() -> InMemoryJobRepository:
    return InMemoryJobRepository()


@pytest.fixture
def module(
    remote: FakeRemote, catalog: FakeCatalog, jobs: InMemoryJobRepository
) -> IngestionModule:
    handlers: dict = {IMPORT_JOB: _run}
    return IngestionModule.build(
        jobs=jobs,
        clock=SystemClock(),
        remote=remote,
        library_ids=catalog,
        libraries=catalog,
        handlers=handlers,
    )


async def test_the_default_branch_is_pinned_and_the_import_is_queued(
    module: IngestionModule, catalog: FakeCatalog, jobs: InMemoryJobRepository
) -> None:
    added = await module.add_library(AddLibraryCommand(url=URL, include_paths=["docs/"]))

    assert (added.library_id, added.ref, added.ref_kind, added.commit_sha) == (
        "/acme/orders",
        "main",
        "branch",
        HEAD,
    )
    (library,) = catalog.added
    assert (library.title, library.host, library.default_branch) == (
        "orders",
        RepositoryHost.GITHUB,
        "main",
    )
    assert library.selection == PathSelection(include=("docs/",))
    job = await jobs.get(JobId(added.job_id))
    assert job is not None
    assert (job.kind, job.library, job.version, job.commit_sha) == (
        IMPORT_JOB,
        "/acme/orders",
        "main",
        HEAD,
    )


async def test_a_tag_and_a_chosen_id(module: IngestionModule, catalog: FakeCatalog) -> None:
    added = await module.add_library(
        AddLibraryCommand(url=URL, library_id="/acme/handbook", ref="v1.0.0")
    )

    assert (added.library_id, added.ref, added.ref_kind, added.commit_sha) == (
        "/acme/handbook",
        "v1.0.0",
        "tag",
        TAG,
    )
    # the default branch is still the repository's, whatever version is imported first
    assert catalog.added[0].default_branch == "main"


async def test_a_taken_id_is_refused_before_any_network_traffic(
    module: IngestionModule, catalog: FakeCatalog, remote: FakeRemote
) -> None:
    catalog.taken.add("/acme/orders")

    with pytest.raises(LibraryIdTakenError):
        await module.add_library(AddLibraryCommand(url=URL))

    assert remote.asked == 0
    assert not catalog.added


@pytest.mark.parametrize(
    ("command", "error"),
    [
        (AddLibraryCommand(url=URL, ref="v9"), UnknownRefError),
        (AddLibraryCommand(url=URL, include_paths=["../x"]), InvalidPathPatternError),
        (AddLibraryCommand(url="--upload-pack=x"), InvalidRepositoryUrlError),
    ],
)
async def test_nothing_is_stored_when_the_request_cannot_be_met(
    module: IngestionModule,
    catalog: FakeCatalog,
    jobs: InMemoryJobRepository,
    command: AddLibraryCommand,
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        await module.add_library(command)

    assert not catalog.added
    assert not await jobs.list_for_library("/acme/orders")


async def test_refs_are_listed_for_the_picker(module: IngestionModule) -> None:
    refs = await module.list_repository_refs(ListRepositoryRefsQuery(url=URL))

    assert refs.default_branch == "main"
    assert [(r.name, r.commit_sha) for r in refs.branches] == [("main", HEAD)]
    assert [(r.name, r.commit_sha) for r in refs.tags] == [("v1.0.0", TAG)]


async def test_the_library_is_removed_when_the_import_cannot_be_queued(
    remote: FakeRemote, catalog: FakeCatalog, jobs: InMemoryJobRepository
) -> None:
    module = IngestionModule.build(  # no handler for `import`: queueing is refused
        jobs=jobs, clock=SystemClock(), remote=remote, library_ids=catalog, libraries=catalog
    )

    with pytest.raises(UnknownJobKindError):
        await module.add_library(AddLibraryCommand(url=URL))

    assert catalog.discarded == ["/acme/orders"]
    assert not await jobs.list_for_library("/acme/orders")


async def test_a_failing_undo_does_not_hide_the_original_error(
    remote: FakeRemote, catalog: FakeCatalog, jobs: InMemoryJobRepository
) -> None:
    class BrokenUndo(FakeCatalog):
        async def discard(self, library_id: str) -> None:
            raise RuntimeError(library_id)

    catalog = BrokenUndo()
    module = IngestionModule.build(
        jobs=jobs, clock=SystemClock(), remote=remote, library_ids=catalog, libraries=catalog
    )

    with pytest.raises(UnknownJobKindError):
        await module.add_library(AddLibraryCommand(url=URL))


async def test_the_refs_list_is_cut_and_flagged(
    remote: FakeRemote, module: IngestionModule
) -> None:
    remote.refs = RemoteRefs(
        default_branch="main",
        refs=tuple(
            RemoteRef(name=f"refs/tags/t{i:05d}", sha=HEAD) for i in range(MAX_LISTED_REFS + 5)
        ),
    )

    refs = await module.list_repository_refs(ListRepositoryRefsQuery(url=URL))

    assert len(refs.tags) == MAX_LISTED_REFS
    assert refs.truncated
    assert refs.tags[0].name == "t00000"


async def test_a_short_list_is_not_flagged(module: IngestionModule) -> None:
    refs = await module.list_repository_refs(ListRepositoryRefsQuery(url=URL))

    assert not refs.truncated
