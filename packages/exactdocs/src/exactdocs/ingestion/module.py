"""Wiring of the ingestion domain: driven adapters in, driving ports out.

It does not pick adapters itself; the composition root (``exactdocs.bootstrap``) passes them in,
together with the job kinds it supports. ``import_job`` builds the import's handler and hook.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Self

from exactdocs.ingestion.models import (
    COLLECT_JOB,
    DEFAULT_GRACE_SECONDS,
    DEFAULT_MAX_ARTICLE_BYTES,
    DEFAULT_MAX_IMPORT_BYTES,
    IMPORT_JOB,
    ImportSource,
    JobKind,
)
from exactdocs.ingestion.ports.driven import (
    Chunker,
    ChunkIndex,
    Collector,
    GitGateway,
    GitRemote,
    JobHandler,
    JobRepository,
    LibraryIds,
    LibrarySources,
    NewLibraries,
    RecoveryHook,
    Removals,
    VersionPublisher,
)
from exactdocs.ingestion.ports.driving import (
    AddLibrary,
    AddVersion,
    CheckRepository,
    EnqueueJob,
    GetJob,
    ListLatestJobs,
    ListLibraryJobs,
    ListRepositoryRefs,
    RecoverJobs,
    RemoveLibrary,
    RemoveVersion,
    RunNextJob,
)
from exactdocs.ingestion.use_cases import (
    AddLibraryUseCase,
    AddVersionUseCase,
    CheckRepositoryUseCase,
    CollectGarbageUseCase,
    DiscardInterruptedImportUseCase,
    EnqueueJobUseCase,
    GetJobUseCase,
    ImportVersionUseCase,
    ListLatestJobsUseCase,
    ListLibraryJobsUseCase,
    ListRepositoryRefsUseCase,
    RecoverJobsUseCase,
    RemoveLibraryUseCase,
    RemoveVersionUseCase,
    RunNextJobUseCase,
)
from exactdocs_kernel import Clock, NotFoundError


class _NoLibrarySources:
    """The default ``sources`` of ``build``: no library is known, so no version can be added."""

    async def get(self, library: str) -> ImportSource:
        message = f"library {library!r} not found"
        raise NotFoundError(message)

    async def imported_versions(self, library: str) -> Mapping[str, str]:
        await self.get(library)
        return {}


@dataclass(frozen=True, slots=True, kw_only=True)
class IngestionModule:
    """The ingestion's driving ports, ready to be exposed by driving adapters."""

    add_library: AddLibrary
    add_version: AddVersion
    check_repository: CheckRepository
    enqueue_job: EnqueueJob
    get_job: GetJob
    list_latest_jobs: ListLatestJobs
    list_library_jobs: ListLibraryJobs
    list_repository_refs: ListRepositoryRefs
    recover_jobs: RecoverJobs
    remove_library: RemoveLibrary
    remove_version: RemoveVersion
    run_next_job: RunNextJob

    @classmethod
    def build(
        cls,
        *,
        jobs: JobRepository,
        clock: Clock,
        remote: GitRemote,
        library_ids: LibraryIds,
        libraries: NewLibraries,
        sources: LibrarySources | None = None,
        removals: Removals,
        index: ChunkIndex,
        handlers: Mapping[JobKind, JobHandler] = MappingProxyType({}),
        recovery_hooks: Mapping[JobKind, RecoveryHook] = MappingProxyType({}),
    ) -> Self:
        """Assemble the use cases around the given driven adapters.

        ``handlers`` maps each job kind to what runs it; ``recovery_hooks`` maps a kind to its
        clean-up after an interrupted run (a kind without one needs none).
        """
        enqueue_job = EnqueueJobUseCase(jobs, clock, handlers)
        return cls(
            add_library=AddLibraryUseCase(remote, library_ids, libraries, enqueue_job),
            add_version=AddVersionUseCase(
                remote, sources or _NoLibrarySources(), jobs, enqueue_job
            ),
            check_repository=CheckRepositoryUseCase(remote, library_ids),
            enqueue_job=enqueue_job,
            get_job=GetJobUseCase(jobs),
            list_latest_jobs=ListLatestJobsUseCase(jobs),
            list_library_jobs=ListLibraryJobsUseCase(jobs),
            list_repository_refs=ListRepositoryRefsUseCase(remote),
            recover_jobs=RecoverJobsUseCase(jobs, clock, recovery_hooks),
            remove_library=RemoveLibraryUseCase(jobs, removals, index, enqueue_job),
            remove_version=RemoveVersionUseCase(jobs, removals, index, enqueue_job),
            run_next_job=RunNextJobUseCase(jobs, clock, handlers),
        )


def import_job(
    *,
    gateway: GitGateway,
    chunker: Chunker,
    sources: LibrarySources,
    versions: VersionPublisher,
    index: ChunkIndex,
    max_article_bytes: int = DEFAULT_MAX_ARTICLE_BYTES,
    max_import_bytes: int = DEFAULT_MAX_IMPORT_BYTES,
) -> tuple[Mapping[JobKind, JobHandler], Mapping[JobKind, RecoveryHook]]:
    """Return the ``handlers`` and ``recovery_hooks`` that make the module import versions."""
    importer = ImportVersionUseCase(
        gateway, chunker, sources, versions, index, max_article_bytes, max_import_bytes
    )
    return {IMPORT_JOB: importer}, {IMPORT_JOB: DiscardInterruptedImportUseCase(versions, index)}


def collect_job(
    *, collectors: Sequence[Collector], grace_seconds: int = DEFAULT_GRACE_SECONDS
) -> Mapping[JobKind, JobHandler]:
    """Return the ``handlers`` entry that makes the module free unused content, in this order."""
    return {COLLECT_JOB: CollectGarbageUseCase(collectors, grace_seconds)}
