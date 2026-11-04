"""Wiring of the ingestion domain: driven adapters in, driving ports out.

It does not pick adapters itself; the composition root (``exactdocs.bootstrap``) passes them in,
together with the job kinds it supports. ``import_job`` builds the import's handler and hook.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Self

from exactdocs.ingestion.models import DEFAULT_MAX_ARTICLE_BYTES, IMPORT_JOB, JobKind
from exactdocs.ingestion.ports.driven import (
    Chunker,
    ChunkIndex,
    GitGateway,
    GitRemote,
    JobHandler,
    JobRepository,
    LibraryIds,
    LibrarySources,
    NewLibraries,
    RecoveryHook,
    VersionPublisher,
)
from exactdocs.ingestion.ports.driving import (
    AddLibrary,
    CheckRepository,
    EnqueueJob,
    GetJob,
    ListLatestJobs,
    ListLibraryJobs,
    ListRepositoryRefs,
    RecoverJobs,
    RunNextJob,
)
from exactdocs.ingestion.use_cases import (
    AddLibraryUseCase,
    CheckRepositoryUseCase,
    DiscardInterruptedImportUseCase,
    EnqueueJobUseCase,
    GetJobUseCase,
    ListLatestJobsUseCase,
    ImportVersionUseCase,
    ListLibraryJobsUseCase,
    ListRepositoryRefsUseCase,
    RecoverJobsUseCase,
    RunNextJobUseCase,
)
from exactdocs_kernel import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class IngestionModule:
    """The ingestion's driving ports, ready to be exposed by driving adapters."""

    add_library: AddLibrary
    check_repository: CheckRepository
    enqueue_job: EnqueueJob
    get_job: GetJob
    list_latest_jobs: ListLatestJobs
    list_library_jobs: ListLibraryJobs
    list_repository_refs: ListRepositoryRefs
    recover_jobs: RecoverJobs
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
            check_repository=CheckRepositoryUseCase(remote, library_ids),
            enqueue_job=enqueue_job,
            get_job=GetJobUseCase(jobs),
            list_latest_jobs=ListLatestJobsUseCase(jobs),
            list_library_jobs=ListLibraryJobsUseCase(jobs),
            list_repository_refs=ListRepositoryRefsUseCase(remote),
            recover_jobs=RecoverJobsUseCase(jobs, clock, recovery_hooks),
            run_next_job=RunNextJobUseCase(jobs, clock, handlers),
        )


def import_job(
    *,
    gateway: GitGateway,
    remote: GitRemote,
    chunker: Chunker,
    sources: LibrarySources,
    versions: VersionPublisher,
    index: ChunkIndex,
    max_article_bytes: int = DEFAULT_MAX_ARTICLE_BYTES,
) -> tuple[Mapping[JobKind, JobHandler], Mapping[JobKind, RecoveryHook]]:
    """Return the ``handlers`` and ``recovery_hooks`` that make the module import versions."""
    importer = ImportVersionUseCase(
        gateway, remote, chunker, sources, versions, index, max_article_bytes
    )
    return {IMPORT_JOB: importer}, {IMPORT_JOB: DiscardInterruptedImportUseCase(versions, index)}
