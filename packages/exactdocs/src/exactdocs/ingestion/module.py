"""Wiring of the ingestion domain: driven adapters in, driving ports out.

It does not pick adapters itself; the composition root (``exactdocs.bootstrap``) passes them in,
together with the job kinds it supports. ``import_job`` builds the import's handler and hook.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Self

from exactdocs.ingestion.constants import (
    COLLECT_JOB,
    DEFAULT_GRACE_SECONDS,
    DEFAULT_IMPORT_BATCH_FILES,
    DEFAULT_MAX_ARTICLE_BYTES,
    DEFAULT_MAX_IMAGE_BYTES,
    DEFAULT_MAX_IMAGES_BYTES,
    DEFAULT_MAX_IMPORT_BYTES,
    IMPORT_JOB,
    LIBRARY_KINDS,
    RECHUNK_JOB,
    REFRESH_JOB,
    REPROCESS_JOB,
    RETAG_JOB,
    JobKind,
)
from exactdocs.ingestion.errors import GitNotInstalledError
from exactdocs.ingestion.models import (
    AutoSync,
    ChunkingConfig,
    Credential,
    FetchedFile,
    GitRename,
    ImportedRef,
    ImportSource,
    Job,
    PathSelection,
    TaggedPath,
    TagRule,
)
from exactdocs.ingestion.ports.driven import (
    AutoSyncStore,
    Checkpoints,
    Chunker,
    ChunkIndex,
    Collector,
    CredentialVault,
    GitGateway,
    GitRemote,
    ImportedTagStore,
    JobHandler,
    JobRepository,
    JobRunner,
    LibraryIds,
    LibrarySettingsStore,
    LibrarySources,
    ManualTagStore,
    NewLibraries,
    RecoveryHook,
    Removals,
    RenameSource,
    RepositoryTree,
    ScheduleSwitch,
    StoredArticleSource,
    VersionCopier,
    VersionPublisher,
)
from exactdocs.ingestion.ports.driving import (
    AddLibrary,
    AddVersion,
    CheckRepository,
    DisableAutoSync,
    EnqueueJob,
    GetAutoSync,
    GetJob,
    GetLibraryAccess,
    ListLatestJobs,
    ListLibraryJobs,
    ListRepositoryRefs,
    PreviewRepository,
    RecoverJobs,
    ReimportVersion,
    RemoveLibrary,
    RemoveVersion,
    RunJob,
    RunNextJob,
    RunScheduledChecks,
    SetAutoSync,
    SubmitQueuedJobs,
    SwitchSchedule,
    SyncLibrary,
    TagArticle,
    UpdateLibrarySettings,
)
from exactdocs.ingestion.use_cases import (
    AddLibraryUseCase,
    AddVersionUseCase,
    CheckRepositoryUseCase,
    CollectGarbageUseCase,
    DisableAutoSyncUseCase,
    DiscardInterruptedImportUseCase,
    EnqueueJobUseCase,
    GetAutoSyncUseCase,
    GetJobUseCase,
    GetLibraryAccessUseCase,
    ImportVersionUseCase,
    ListLatestJobsUseCase,
    ListLibraryJobsUseCase,
    ListRepositoryRefsUseCase,
    PreviewRepositoryUseCase,
    RechunkLibraryUseCase,
    RecoverJobsUseCase,
    ReimportVersionUseCase,
    RemoveLibraryUseCase,
    RemoveVersionUseCase,
    ReprocessLibraryUseCase,
    RetagLibraryUseCase,
    RunJobUseCase,
    RunNextJobUseCase,
    RunScheduledChecksUseCase,
    SetAutoSyncUseCase,
    SubmitQueuedJobsUseCase,
    SwitchScheduleUseCase,
    SyncLibraryUseCase,
    TagArticleUseCase,
    TagLocks,
    UpdateLibrarySettingsUseCase,
)
from exactdocs_kernel import Clock, NotFoundError


class _NoLibrarySources:
    """The default ``sources`` of ``build``: no library is known, so no version can be added."""

    async def get(self, library: str) -> ImportSource:
        message = f"library {library!r} not found"
        raise NotFoundError(message)

    async def imported_versions(self, library: str) -> list[ImportedRef]:
        await self.get(library)
        return []

    async def renames_of(self, library: str, ref: str) -> list[GitRename]:
        del library, ref
        return []


class _InlineSteps:
    """``Checkpoints`` that only run each step: for work done inside another durable step."""

    async def step[T](self, name: str, run: Callable[[], Awaitable[T]], /) -> T:
        del name
        return await run()


class _NoSettings:
    """The default ``settings`` of ``build``: no library is known, so none can be edited."""

    async def save(
        self,
        library: str,
        selection: PathSelection,
        tag_rules: Sequence[TagRule],
        chunking: ChunkingConfig,
    ) -> None:
        del selection, tag_rules, chunking
        message = f"library {library!r} not found"
        raise NotFoundError(message)


class _NoManualTags:
    """The default ``manual_tags`` of ``build``: no library is known, so none can be tagged."""

    async def set_tags(self, library: str, path: str, tags: Sequence[str]) -> TaggedPath:
        del path, tags
        message = f"library {library!r} not found"
        raise NotFoundError(message)


class _NoTree:
    """The default ``tree`` of ``build``: no git to list a commit with.

    (Not ``MissingGit``: the core does not import adapters.)
    """

    async def list_files(self, repository: object, commit_sha: str, **_: object) -> list[str]:
        del repository, commit_sha
        raise GitNotInstalledError

    async def read_file(
        self, repository: object, commit_sha: str, path: str, **_: object
    ) -> FetchedFile:
        del repository, commit_sha, path
        raise GitNotInstalledError


class _NoCredentials:
    """The default ``vault`` of ``build``: nothing is kept, so only public repositories work."""

    async def save(self, library: str, scope: str, credential: Credential) -> None:
        del library, scope, credential

    async def load(self, library: str, scope: str) -> Credential | None:
        del library, scope

    async def delete(self, library: str) -> None:
        del library

    async def has(self, library: str) -> bool:
        del library
        return False


class _NoAutoSyncs:
    """The default ``auto_syncs`` of ``build``: nothing is kept, so no library is checked."""

    async def get(self, library: str) -> AutoSync | None:
        del library

    async def save(self, auto_sync: AutoSync) -> None:
        del auto_sync

    async def delete(self, library: str) -> None:
        del library

    async def list_all(self) -> list[AutoSync]:
        return []

    async def record_check(self, read: AutoSync, checked: AutoSync) -> bool:
        del read, checked
        return False


class _NoSwitch:
    """The default ``schedule_switch`` of ``build``: no tick to turn on or off."""

    async def turn(self, *, on: bool) -> None:
        del on


class _NoRunner:
    """The default ``runner`` of ``build``: jobs wait in the repository for ``RunNextJob``."""

    async def submit(self, job: Job) -> None:
        del job


@dataclass(frozen=True, slots=True, kw_only=True)
class IngestionModule:
    """The ingestion's driving ports, ready to be exposed by driving adapters."""

    add_library: AddLibrary
    add_version: AddVersion
    check_repository: CheckRepository
    disable_auto_sync: DisableAutoSync
    enqueue_job: EnqueueJob
    get_auto_sync: GetAutoSync
    get_job: GetJob
    get_library_access: GetLibraryAccess
    list_latest_jobs: ListLatestJobs
    list_library_jobs: ListLibraryJobs
    list_repository_refs: ListRepositoryRefs
    preview_repository: PreviewRepository
    recover_jobs: RecoverJobs
    reimport_version: ReimportVersion
    remove_library: RemoveLibrary
    remove_version: RemoveVersion
    run_job: RunJob
    run_next_job: RunNextJob
    run_scheduled_checks: RunScheduledChecks
    set_auto_sync: SetAutoSync
    submit_queued_jobs: SubmitQueuedJobs
    switch_schedule: SwitchSchedule
    sync_library: SyncLibrary
    tag_article: TagArticle
    update_library_settings: UpdateLibrarySettings

    @classmethod
    def build(
        cls,
        *,
        jobs: JobRepository,
        clock: Clock,
        remote: GitRemote,
        tree: RepositoryTree | None = None,
        library_ids: LibraryIds,
        libraries: NewLibraries,
        sources: LibrarySources | None = None,
        removals: Removals,
        index: ChunkIndex,
        vault: CredentialVault | None = None,
        handlers: Mapping[JobKind, JobHandler] = MappingProxyType({}),
        recovery_hooks: Mapping[JobKind, RecoveryHook] = MappingProxyType({}),
        runner: JobRunner | None = None,
        manual_tags: ManualTagStore | None = None,
        tag_locks: TagLocks | None = None,
        auto_syncs: AutoSyncStore | None = None,
        schedule_switch: ScheduleSwitch | None = None,
        settings: LibrarySettingsStore | None = None,
    ) -> Self:
        """Assemble the use cases around the given driven adapters.

        ``handlers`` maps each job kind to what runs it; ``recovery_hooks`` maps a kind to its
        clean-up after an interrupted run (a kind without one needs none). With ``manual_tags``
        pass ``tag_locks``, the object given to ``import_job``, so tagging and an import's
        activation take turns. ``tree`` also reads a repository's ``context7.json`` when a
        library is added; without it there is none. ``runner`` is told about every queued job;
        without one, jobs wait for ``run_next_job``. ``auto_syncs`` keeps the libraries'
        scheduled checks (``run_scheduled_checks`` is one tick); without it none is kept.
        ``schedule_switch`` turns the tick on while any library has a schedule. ``settings``
        stores edited paths and tag rules; it needs the ``reprocess`` and ``retag`` handlers
        of ``import_job``.
        """
        if manual_tags is not None and tag_locks is None:
            message = "manual_tags needs the tag_locks given to import_job"
            raise TypeError(message)
        if settings is not None and not handlers.keys() >= LIBRARY_KINDS:
            message = "settings needs the reprocess, rechunk and retag handlers of import_job"
            raise TypeError(message)
        runner = runner or _NoRunner()
        enqueue_job = EnqueueJobUseCase(jobs=jobs, clock=clock, handlers=handlers, runner=runner)
        none = _NoLibrarySources()
        vault = vault or _NoCredentials()
        schedules = auto_syncs or _NoAutoSyncs()
        switch = schedule_switch or _NoSwitch()
        remove_version = RemoveVersionUseCase(
            jobs=jobs, removals=removals, index=index, enqueue_job=enqueue_job
        )
        sync_library = SyncLibraryUseCase(
            remote=remote,
            sources=sources or none,
            jobs=jobs,
            clock=clock,
            enqueue_job=enqueue_job,
            vault=vault,
        )
        return cls(
            add_library=AddLibraryUseCase(
                remote=remote,
                library_ids=library_ids,
                libraries=libraries,
                enqueue_job=enqueue_job,
                vault=vault,
                tree=tree,
            ),
            add_version=AddVersionUseCase(
                remote=remote,
                sources=sources or _NoLibrarySources(),
                jobs=jobs,
                enqueue_job=enqueue_job,
                vault=vault,
            ),
            check_repository=CheckRepositoryUseCase(remote=remote, library_ids=library_ids),
            disable_auto_sync=DisableAutoSyncUseCase(
                sources=sources or none, schedules=schedules, switch=switch
            ),
            enqueue_job=enqueue_job,
            get_auto_sync=GetAutoSyncUseCase(sources=sources or none, schedules=schedules),
            get_job=GetJobUseCase(jobs=jobs),
            get_library_access=GetLibraryAccessUseCase(vault=vault, library_ids=library_ids),
            list_latest_jobs=ListLatestJobsUseCase(jobs=jobs),
            list_library_jobs=ListLibraryJobsUseCase(jobs=jobs),
            list_repository_refs=ListRepositoryRefsUseCase(remote=remote),
            preview_repository=PreviewRepositoryUseCase(remote=remote, tree=tree or _NoTree()),
            recover_jobs=RecoverJobsUseCase(
                jobs=jobs, clock=clock, hooks=recovery_hooks, runner=runner
            ),
            reimport_version=ReimportVersionUseCase(
                remote=remote,
                sources=sources or none,
                jobs=jobs,
                enqueue_job=enqueue_job,
                vault=vault,
            ),
            remove_library=RemoveLibraryUseCase(
                jobs=jobs,
                removals=removals,
                index=index,
                enqueue_job=enqueue_job,
                vault=vault,
                schedules=schedules,
                switch=switch,
            ),
            remove_version=remove_version,
            run_job=RunJobUseCase(jobs=jobs, clock=clock, handlers=handlers, hooks=recovery_hooks),
            run_next_job=RunNextJobUseCase(jobs=jobs, clock=clock, handlers=handlers),
            run_scheduled_checks=RunScheduledChecksUseCase(
                schedules=schedules,
                sources=sources or none,
                remote=remote,
                vault=vault,
                jobs=jobs,
                clock=clock,
                enqueue_job=enqueue_job,
                sync_library=sync_library,
                remove_version=remove_version,
                switch=switch,
            ),
            set_auto_sync=SetAutoSyncUseCase(
                sources=sources or none, schedules=schedules, switch=switch
            ),
            submit_queued_jobs=SubmitQueuedJobsUseCase(jobs=jobs, runner=runner),
            switch_schedule=SwitchScheduleUseCase(schedules=schedules, switch=switch),
            sync_library=sync_library,
            tag_article=TagArticleUseCase(
                tags=manual_tags or _NoManualTags(), index=index, locks=tag_locks or TagLocks()
            ),
            update_library_settings=UpdateLibrarySettingsUseCase(
                sources=sources or none,
                settings=settings or _NoSettings(),
                jobs=jobs,
                enqueue_job=enqueue_job,
            ),
        )


def import_job(
    *,
    gateway: GitGateway,
    chunker: Chunker,
    sources: LibrarySources,
    versions: VersionPublisher,
    index: ChunkIndex,
    vault: CredentialVault | None = None,
    max_article_bytes: int = DEFAULT_MAX_ARTICLE_BYTES,
    max_import_bytes: int = DEFAULT_MAX_IMPORT_BYTES,
    renames: RenameSource | None = None,
    stored: StoredArticleSource | None = None,
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
    max_images_bytes: int = DEFAULT_MAX_IMAGES_BYTES,
    tag_locks: TagLocks,
    imported_tags: ImportedTagStore,
    copier: VersionCopier,
    checkpoints: Checkpoints | None = None,
    batch_files: int = DEFAULT_IMPORT_BATCH_FILES,
) -> tuple[Mapping[JobKind, JobHandler], Mapping[JobKind, RecoveryHook]]:
    """Return the ``handlers`` and ``recovery_hooks`` that make the module import versions.

    Pass the same ``tag_locks`` to ``IngestionModule.build`` (see ``TagArticleUseCase``).
    The handlers re-process a library after a settings edit too: ``reprocess`` re-imports every
    version; ``rechunk`` re-chunks (and re-tags) the copies ``copier`` makes of what each
    version serves; ``retag`` re-tags them from what ``imported_tags`` has stored.
    ``stored`` lets an import take the files earlier imports stored instead of parsing them.
    ``checkpoints`` makes the import's steps durable (one per ``batch_files`` files parsed and
    chunked); without it an interrupted import starts over.
    """
    importer = ImportVersionUseCase(
        gateway=gateway,
        chunker=chunker,
        sources=sources,
        versions=versions,
        index=index,
        vault=vault or _NoCredentials(),
        max_article_bytes=max_article_bytes,
        max_import_bytes=max_import_bytes,
        renames=renames,
        stored=stored,
        max_image_bytes=max_image_bytes,
        max_images_bytes=max_images_bytes,
        batch_files=batch_files,
        tag_locks=tag_locks,
    )
    if checkpoints is not None:
        importer = replace(importer, checkpoints=checkpoints)
    refresher = replace(importer, refresh=True)
    hook = DiscardInterruptedImportUseCase(versions=versions, index=index)
    steps = importer.checkpoints
    # One durable step per version: the re-import inside it records none of its own.
    inline = replace(refresher, checkpoints=_InlineSteps())
    handlers: dict[JobKind, JobHandler] = {
        IMPORT_JOB: importer,
        REFRESH_JOB: refresher,
        REPROCESS_JOB: ReprocessLibraryUseCase(sources=sources, importer=inline, checkpoints=steps),
        RECHUNK_JOB: RechunkLibraryUseCase(
            sources=sources,
            copier=copier,
            chunker=chunker,
            tags=imported_tags,
            versions=versions,
            index=index,
            tag_locks=tag_locks,
            importer=inline,
            checkpoints=steps,
        ),
        RETAG_JOB: RetagLibraryUseCase(
            sources=sources, tags=imported_tags, index=index, tag_locks=tag_locks, checkpoints=steps
        ),
    }
    # A re-tag writes each version in one transaction and is safe to redo: nothing to clean up.
    hooks = {IMPORT_JOB: hook, REFRESH_JOB: hook, REPROCESS_JOB: hook, RECHUNK_JOB: hook}
    return handlers, hooks


def collect_job(
    *, collectors: Sequence[Collector], grace_seconds: int = DEFAULT_GRACE_SECONDS
) -> Mapping[JobKind, JobHandler]:
    """Return the ``handlers`` entry that makes the module free unused content, in this order."""
    return {COLLECT_JOB: CollectGarbageUseCase(collectors=collectors, grace_seconds=grace_seconds)}
