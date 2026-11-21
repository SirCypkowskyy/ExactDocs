"""Wiring of the ingestion domain: driven adapters in, driving ports out.

It does not pick adapters itself; the composition root (``exactdocs.bootstrap``) passes them in,
together with the job kinds it supports. ``import_job`` builds the import's handler and hook.
"""

from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from types import MappingProxyType
from typing import Never, Self

from exactdocs.ingestion.constants import (
    COLLECT_JOB,
    DEFAULT_GRACE_SECONDS,
    DEFAULT_IMPORT_BATCH_FILES,
    DEFAULT_MAX_ARTICLE_BYTES,
    DEFAULT_MAX_IMAGE_BYTES,
    DEFAULT_MAX_IMAGES_BYTES,
    DEFAULT_MAX_IMPORT_BYTES,
    EMBED_AFTER_KINDS,
    EMBED_JOB,
    IMPORT_JOB,
    LIBRARY_KINDS,
    PUSH_JOB,
    RECHUNK_JOB,
    REFRESH_JOB,
    REPROCESS_JOB,
    RETAG_JOB,
    JobKind,
)
from exactdocs.ingestion.errors import GitNotInstalledError
from exactdocs.ingestion.models import (
    Access,
    AutoSync,
    ChunkingConfig,
    Credential,
    GitRename,
    ImportedRef,
    Job,
    KnownLibrary,
    PathSelection,
    TagRule,
    Webhook,
    WebhookDelivery,
)
from exactdocs.ingestion.ports.driven import (
    AccessPolicy,
    AutoSyncStore,
    Checkpoints,
    Chunker,
    ChunkIndex,
    Collector,
    CredentialVault,
    GitGateway,
    GitRemote,
    GuidancePolicy,
    ImportedTagStore,
    JobHandler,
    JobRepository,
    JobRunner,
    KnownLibraries,
    LibraryIds,
    LibraryLocks,
    LibrarySettingsStore,
    LibrarySources,
    LibraryTexts,
    ManualTagStore,
    MarkupConverter,
    NewLibraries,
    RecoveryHook,
    Removals,
    RenameSource,
    RepositoryFiles,
    RepositoryTree,
    ScheduleSwitch,
    StoredArticleSource,
    VersionCopier,
    VersionEmbedder,
    VersionPublisher,
    WebhookDeliveries,
    WebhookSecrets,
)
from exactdocs.ingestion.ports.driving import (
    AddLibrary,
    AddVersion,
    ApplySources,
    CancelJob,
    CheckRepository,
    DisableAutoSync,
    DisableWebhook,
    EnqueueJob,
    GetAutoSync,
    GetJob,
    GetLibraryAccess,
    GetWebhook,
    ListLatestJobs,
    ListLibraryJobs,
    ListRepositoryRefs,
    PlanSources,
    PreviewRepository,
    QueueEmbedding,
    ReceiveWebhook,
    RecoverJobs,
    ReimportVersion,
    RemoveLibrary,
    RemoveVersion,
    RunJob,
    RunNextJob,
    RunScheduledChecks,
    SetAutoSync,
    SetWebhook,
    SubmitQueuedJobs,
    SwitchSchedule,
    SyncLibrary,
    TagArticle,
    UpdateLibrarySettings,
)
from exactdocs.ingestion.use_cases import (
    AddLibraryUseCase,
    AddVersionUseCase,
    ApplySourcesUseCase,
    AutoImports,
    CancelJobUseCase,
    CheckRepositoryUseCase,
    CollectGarbageUseCase,
    DisableAutoSyncUseCase,
    DisableWebhookUseCase,
    DiscardInterruptedImportUseCase,
    EmbedAfterJob,
    EmbeddingQueue,
    EmbedVersionUseCase,
    EnqueueJobUseCase,
    GetAutoSyncUseCase,
    GetJobUseCase,
    GetLibraryAccessUseCase,
    GetWebhookUseCase,
    ImportVersionUseCase,
    ListLatestJobsUseCase,
    ListLibraryJobsUseCase,
    ListRepositoryRefsUseCase,
    PlanSourcesUseCase,
    PreviewRepositoryUseCase,
    PushJobUseCase,
    QueueEmbeddingUseCase,
    ReceiveWebhookUseCase,
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
    SetWebhookUseCase,
    SourcesReader,
    StopOnCancel,
    SubmitQueuedJobsUseCase,
    SwitchScheduleUseCase,
    SyncLibraryUseCase,
    TagArticleUseCase,
    TagLocks,
    UpdateLibrarySettingsUseCase,
)
from exactdocs_kernel import Clock, NotFoundError


class _EveryoneMayDoAnything:
    """The default ``access`` of ``build``: no roles, as in a local process the owner runs."""

    async def can_create(self, library: str | None = None) -> bool:
        """Allow creation by internal callers.

        Args:
            library: The proposed ID, if known.

        Returns:
            Always True.
        """
        del library
        return True

    async def allows(self, library: str, access: Access) -> bool:
        """Allow everything.

        Args:
            library: The library.
            access: The role the action needs.

        Returns:
            Always ``True``.
        """
        del library, access
        return True

    async def readable(self, libraries: Collection[str]) -> frozenset[str]:
        """Allow reading every library.

        Args:
            libraries: Library IDs.

        Returns:
            All of them, lower-case.
        """
        return frozenset(library.casefold() for library in libraries)


_open_access = _EveryoneMayDoAnything()


class _NoLibrarySources:
    """The default ``sources`` of ``build``: no library is known, so no version can be added."""

    async def get(self, library: str) -> Never:
        """Refuse: no library is known.

        Args:
            library: The library ID.

        Raises:
            NotFoundError: Always.
        """
        message = f"library {library!r} not found"
        raise NotFoundError(message)

    async def imported_versions(self, library: str) -> list[ImportedRef]:
        """Refuse: no library is known.

        Args:
            library: The library ID.

        Returns:
            Never: ``get`` raises ``NotFoundError``.
        """
        await self.get(library)
        return []

    async def renames_of(self, library: str, ref: str) -> list[GitRename]:
        """Know no renames.

        Args:
            library: The library ID.
            ref: The version's ref.

        Returns:
            No renames.
        """
        del library, ref
        return []


class _InlineSteps:
    """``Checkpoints`` that only run each step: for work done inside another durable step."""

    async def step[T](self, name: str, run: Callable[[], Awaitable[T]], /) -> T:
        """Run the step; nothing is recorded.

        Args:
            name: The step's name.
            run: Runs the step.

        Returns:
            What ``run`` returned.
        """
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
        """Refuse: no library is known.

        Args:
            library: The library ID.
            selection: The paths to import.
            tag_rules: Tags given to articles by path.
            chunking: How articles are cut into chunks.

        Raises:
            NotFoundError: Always.
        """
        del selection, tag_rules, chunking
        message = f"library {library!r} not found"
        raise NotFoundError(message)


class _NoTexts:
    """The default ``texts`` of ``build``: no library is known, so none can be edited."""

    async def save(self, library: str, *, title: str | None, description: str | None) -> None:
        """Refuse: no library is known.

        Args:
            library: The library ID.
            title: The new title.
            description: The new description.

        Raises:
            NotFoundError: Always.
        """
        del title, description
        message = f"library {library!r} not found"
        raise NotFoundError(message)


class _NoManualTags:
    """The default ``manual_tags`` of ``build``: no library is known, so none can be tagged."""

    async def set_tags(self, library: str, path: str, tags: Sequence[str]) -> Never:
        """Refuse: no library is known.

        Args:
            library: The library ID.
            path: The article's path.
            tags: The manual tags.

        Raises:
            NotFoundError: Always.
        """
        del path, tags
        message = f"library {library!r} not found"
        raise NotFoundError(message)


class _NoTree:
    """The default ``tree`` of ``build``: no git to list a commit with.

    (Not ``MissingGit``: the core does not import adapters.)
    """

    async def list_files(self, repository: object, commit_sha: str, **_: object) -> Never:
        """Refuse: there is no git.

        Args:
            repository: The repository.
            commit_sha: The commit.
            **_: The port's other arguments.

        Raises:
            GitNotInstalledError: Always.
        """
        del repository, commit_sha
        raise GitNotInstalledError

    async def read_file(self, repository: object, commit_sha: str, path: str, **_: object) -> Never:
        """Refuse: there is no git.

        Args:
            repository: The repository.
            commit_sha: The commit.
            path: The file's name.
            **_: The port's other arguments.

        Raises:
            GitNotInstalledError: Always.
        """
        del repository, commit_sha, path
        raise GitNotInstalledError


class _NoCredentials:
    """The default ``vault`` of ``build``: nothing is kept, so only public repositories work."""

    async def save(self, library: str, scope: str, credential: Credential) -> None:
        """Keep nothing.

        Args:
            library: The library ID.
            scope: Where the credential may be offered.
            credential: The token or deploy key.
        """
        del library, scope, credential

    async def load(self, library: str, scope: str) -> Credential | None:
        """Find nothing.

        Args:
            library: The library ID.
            scope: The library's credential scope.

        Returns:
            Always ``None``: no library has a credential.
        """
        del library, scope
        return None

    async def delete(self, library: str) -> None:
        """Forget nothing: nothing is kept.

        Args:
            library: The library ID.
        """
        del library

    async def has(self, library: str) -> bool:
        """Tell that the library has no credential.

        Args:
            library: The library ID.

        Returns:
            Always False.
        """
        del library
        return False


class _NoAutoSyncs:
    """The default ``auto_syncs`` of ``build``: nothing is kept, so no library is checked."""

    async def get(self, library: str) -> AutoSync | None:
        """Find nothing.

        Args:
            library: The library ID.

        Returns:
            Always ``None``: no library is checked on its own.
        """
        del library
        return None

    async def save(self, auto_sync: AutoSync) -> None:
        """Keep nothing.

        Args:
            auto_sync: The schedule.
        """
        del auto_sync

    async def delete(self, library: str) -> None:
        """Forget nothing: nothing is kept.

        Args:
            library: The library ID.
        """
        del library

    async def list_all(self) -> list[AutoSync]:
        """List no schedule.

        Returns:
            No schedules.
        """
        return []

    async def record_check(self, read: AutoSync, checked: AutoSync) -> bool:
        """Store nothing.

        Args:
            read: The schedule as the check read it.
            checked: The same schedule with the check's result.

        Returns:
            Always False: no schedule is stored.
        """
        del read, checked
        return False


class _NoKnownLibraries:
    """The default ``known_libraries`` of ``build``: no library is known."""

    async def all(self) -> list[KnownLibrary]:
        """List no library.

        Returns:
            Nothing.
        """
        return []


class _NoWebhooks:
    """The default ``webhooks`` of ``build``: no library has a secret, so every delivery fails."""

    async def save(self, webhook: Webhook) -> None:
        """Refuse: without a store a secret would be shown that never works.

        Args:
            webhook: The webhook.

        Raises:
            NotImplementedError: Always.
        """
        del webhook
        message = "no webhook store was given to IngestionModule.build"
        raise NotImplementedError(message)

    async def get(self, library: str) -> Webhook | None:
        """Find nothing.

        Args:
            library: The library ID.

        Returns:
            Always ``None``.
        """
        del library
        return None

    async def created_at(self, library: str) -> datetime | None:
        """Find nothing.

        Args:
            library: The library ID.

        Returns:
            Always ``None``.
        """
        del library
        return None

    async def delete(self, library: str) -> None:
        """Forget nothing: nothing is kept.

        Args:
            library: The library ID.
        """
        del library


class _NoDeliveries:
    """The default ``webhook_deliveries`` of ``build``: nothing is remembered."""

    async def record(self, delivery: WebhookDelivery, *, prune_before: datetime) -> bool:
        """Remember nothing: every delivery is new.

        Args:
            delivery: The delivery.
            prune_before: Unused.

        Returns:
            Always True.
        """
        del delivery, prune_before
        return True

    async def forget(self, delivery: WebhookDelivery) -> None:
        """Forget nothing.

        Args:
            delivery: The delivery.
        """
        del delivery

    async def delete_for(self, library: str) -> None:
        """Forget nothing.

        Args:
            library: The library ID.
        """
        del library


def _wrapped(
    kind: JobKind,
    handler: JobHandler,
    wrap_handler: Callable[[JobKind, JobHandler], JobHandler] | None,
) -> JobHandler:
    """Wrap a handler built inside ``build``, as ``build``'s ``wrap_handler`` says.

    Args:
        kind: The handler's job kind.
        handler: The handler, as built.
        wrap_handler: Wraps it, given its kind; None: it runs as built.

    Returns:
        The handler to register for ``kind``.
    """
    return handler if wrap_handler is None else wrap_handler(kind, handler)


class _NoSwitch:
    """The default ``schedule_switch`` of ``build``: no tick to turn on or off."""

    async def turn(self, *, on: bool) -> None:
        """Do nothing: there is no tick.

        Args:
            on: Whether the tick should run.
        """
        del on


class _NoRunner:
    """The default ``runner`` of ``build``: jobs wait in the repository for ``RunNextJob``."""

    async def submit(self, job: Job) -> None:
        """Do nothing: the job waits in the repository.

        Args:
            job: The queued job.
        """
        del job


@dataclass(frozen=True, slots=True, kw_only=True)
class IngestionModule:
    """The ingestion's driving ports, ready to be exposed by driving adapters."""

    add_library: AddLibrary
    """Creates a library from a git URL and queues its first import."""
    add_version: AddVersion
    """Pins another ref of a library and queues its import."""
    apply_sources: ApplySources
    """Applies a sources file library by library."""
    cancel_job: CancelJob
    """Cancels a queued or running job."""
    check_repository: CheckRepository
    """Validates a git URL and proposes a library ID, saving nothing."""
    disable_auto_sync: DisableAutoSync
    """Turns a library's scheduled check off."""
    disable_webhook: DisableWebhook
    """Forgets a library's webhook secret."""
    enqueue_job: EnqueueJob
    """Queues a job of a registered kind."""
    get_auto_sync: GetAutoSync
    """Reads a library's scheduled check."""
    get_job: GetJob
    """Reads one job."""
    get_library_access: GetLibraryAccess
    """Says whether a library has a stored credential."""
    get_webhook: GetWebhook
    """Says whether a library's webhook is on."""
    list_latest_jobs: ListLatestJobs
    """Lists the newest job of every (library, version)."""
    list_library_jobs: ListLibraryJobs
    """Lists a page of a library's jobs."""
    list_repository_refs: ListRepositoryRefs
    """Lists a repository's branches and tags."""
    plan_sources: PlanSources
    """Compares a sources file with the instance, writing nothing."""
    preview_repository: PreviewRepository
    """Lists the files an import would take, importing nothing."""
    queue_embedding: QueueEmbedding
    """Queues the ``embed`` jobs of the versions not fully embedded."""
    receive_webhook: ReceiveWebhook
    """Verifies a forge's push delivery and queues its ``push`` jobs."""
    recover_jobs: RecoverJobs
    """On start: cleans up after interrupted jobs and hands the queued ones to the runner."""
    reimport_version: ReimportVersion
    """Re-imports a tag version that moved upstream."""
    remove_library: RemoveLibrary
    """Removes a library and its versions, and queues the job that frees their content."""
    remove_version: RemoveVersion
    """Removes a version, and queues the job that frees its content."""
    run_job: RunJob
    """Runs one job to its end."""
    run_next_job: RunNextJob
    """Runs the next job that may run, if any."""
    run_scheduled_checks: RunScheduledChecks
    """Runs one tick of the scheduled checks."""
    set_auto_sync: SetAutoSync
    """Turns a library's scheduled check on, or changes it."""
    set_webhook: SetWebhook
    """Creates or rotates a library's webhook secret."""
    submit_queued_jobs: SubmitQueuedJobs
    """Hands every queued job to the runner again."""
    switch_schedule: SwitchSchedule
    """Turns the tick on while any library has a schedule, off otherwise."""
    sync_library: SyncLibrary
    """Re-syncs a library's branch versions."""
    tag_article: TagArticle
    """Sets the manual tags of an article path for every version of its library."""
    update_library_settings: UpdateLibrarySettings
    """Replaces a library's paths, tag rules and chunking and re-processes its versions."""

    @classmethod
    def build(
        cls,
        *,
        jobs: JobRepository,
        clock: Clock,
        remote: GitRemote,
        tree: RepositoryTree | None = None,
        library_ids: LibraryIds,
        creation_library_ids: LibraryIds | None = None,
        libraries: NewLibraries,
        sources: LibrarySources | None = None,
        removals: Removals,
        index: ChunkIndex,
        vault: CredentialVault | None = None,
        handlers: Mapping[JobKind, JobHandler] = MappingProxyType({}),
        recovery_hooks: Mapping[JobKind, RecoveryHook] = MappingProxyType({}),
        runner: JobRunner | None = None,
        manual_tags: ManualTagStore | None = None,
        tag_locks: LibraryLocks | None = None,
        settings_locks: LibraryLocks | None = None,
        auto_syncs: AutoSyncStore | None = None,
        schedule_switch: ScheduleSwitch | None = None,
        settings: LibrarySettingsStore | None = None,
        texts: LibraryTexts | None = None,
        embedder: VersionEmbedder | None = None,
        checkpoints: Checkpoints | None = None,
        known_libraries: KnownLibraries | None = None,
        webhooks: WebhookSecrets | None = None,
        webhook_deliveries: WebhookDeliveries | None = None,
        wrap_handler: Callable[[JobKind, JobHandler], JobHandler] | None = None,
        access: AccessPolicy = _open_access,
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
        of ``import_job``. ``settings_locks`` orders the edits of one library (another object
        than ``tag_locks``); without it they take turns within this process only. ``embedder``
        adds the ``embed`` job (one version embedded in the background, a durable step per batch
        through ``checkpoints``) and makes every job that stores chunks queue the embedding of
        what it stored. ``webhooks`` keeps the libraries' push webhook secrets and
        ``webhook_deliveries`` the deliveries seen; the ``push`` job they queue is always
        registered (it syncs one branch or auto-imports after one tag). ``wrap_handler`` wraps
        that ``push`` handler, which is built here (for example in a span, as the given
        ``handlers`` already are).

        Args:
            jobs: Where jobs are stored.
            clock: Tells the time.
            remote: Lists a repository's refs.
            tree: Lists a commit's files and reads its root files; None: no git for previews.
            library_ids: Tells which library IDs are taken.
            creation_library_ids: Creation-authorized ID probe; defaults to library_ids.
            libraries: Where new libraries go.
            sources: Where a library's articles come from; None: no library is known.
            removals: Removes versions and libraries from the catalog.
            index: Where chunks are stored and searched.
            vault: Where credentials are kept; None: only public repositories work.
            handlers: What runs each job kind.
            recovery_hooks: What cleans up after an interrupted job, by kind.
            runner: What runs queued jobs; None: they wait for ``run_next_job``.
            manual_tags: Where manual tags are kept; None: no library can be tagged.
            tag_locks: The locks ``import_job`` got; required with ``manual_tags``.
            settings_locks: Order the settings edits of one library.
            auto_syncs: Where the scheduled checks are kept.
            schedule_switch: Turns the tick on or off.
            settings: Where edited settings are stored; None: no library can be edited.
            texts: Where a library's title and description are stored; None: none can be.
            embedder: Embeds versions; None: no ``embed`` job.
            checkpoints: Makes the ``embed`` job's batches durable steps.
            known_libraries: Lists the libraries, for a sources file; None: none is known.
            webhooks: Where webhook secrets are kept; None: no library can have one.
            webhook_deliveries: Where deliveries are remembered; None: none is.
            wrap_handler: Wraps the ``push`` handler, given its kind; None: it runs as built.
            access: Library roles: what the caller may do with a library; everything without it.

        Returns:
            The module.

        Raises:
            TypeError: ``manual_tags`` without ``tag_locks``, or ``settings`` without the
                ``reprocess``, ``rechunk`` and ``retag`` handlers.
        """
        if manual_tags is not None and tag_locks is None:
            message = "manual_tags needs the tag_locks given to import_job"
            raise TypeError(message)
        if settings is not None and not handlers.keys() >= LIBRARY_KINDS:
            message = "settings needs the reprocess, rechunk and retag handlers of import_job"
            raise TypeError(message)
        runner = runner or _NoRunner()
        # The `push` handler needs the use cases built over `enqueue_job`: added below, to this
        # same mapping, which `enqueue_job` and the runners read when a job comes.
        kinds: dict[JobKind, JobHandler] = dict(handlers)
        embedding = None
        if embedder is not None:
            embedding = EmbeddingQueue(jobs=jobs, runner=runner, clock=clock, embedder=embedder)
            kinds = {
                **{
                    kind: EmbedAfterJob(inner=handler, queue=embedding)
                    if kind in EMBED_AFTER_KINDS
                    else handler
                    for kind, handler in kinds.items()
                },
                EMBED_JOB: EmbedVersionUseCase(
                    embedder=embedder,
                    queue=embedding,
                    # A cancelled job stops before its next batch; the batches done are kept.
                    checkpoints=StopOnCancel(inner=checkpoints or _InlineSteps()),
                ),
            }
        enqueue_job = EnqueueJobUseCase(jobs=jobs, clock=clock, handlers=kinds, runner=runner)
        sources = sources or _NoLibrarySources()
        vault = vault or _NoCredentials()
        schedules = auto_syncs or _NoAutoSyncs()
        switch = schedule_switch or _NoSwitch()
        remove_version = RemoveVersionUseCase(
            jobs=jobs, removals=removals, index=index, enqueue_job=enqueue_job, access=access
        )
        sync_library = SyncLibraryUseCase(
            remote=remote,
            sources=sources,
            jobs=jobs,
            clock=clock,
            enqueue_job=enqueue_job,
            vault=vault,
            access=access,
        )
        add_library = AddLibraryUseCase(
            access=access,
            remote=remote,
            library_ids=creation_library_ids or library_ids,
            libraries=libraries,
            enqueue_job=enqueue_job,
            vault=vault,
            tree=tree,
        )
        add_version = AddVersionUseCase(
            remote=remote,
            sources=sources,
            jobs=jobs,
            enqueue_job=enqueue_job,
            vault=vault,
            access=access,
        )
        remove_library = RemoveLibraryUseCase(
            jobs=jobs,
            removals=removals,
            index=index,
            enqueue_job=enqueue_job,
            vault=vault,
            schedules=schedules,
            switch=switch,
            webhooks=webhooks or _NoWebhooks(),
            deliveries=webhook_deliveries or _NoDeliveries(),
            access=access,
        )
        update_library_settings = UpdateLibrarySettingsUseCase(
            sources=sources,
            settings=settings or _NoSettings(),
            jobs=jobs,
            enqueue_job=enqueue_job,
            locks=settings_locks or TagLocks(),
            access=access,
        )
        kinds[PUSH_JOB] = _wrapped(
            PUSH_JOB,
            PushJobUseCase(
                sync_library=sync_library,
                sources=sources,
                remote=remote,
                vault=vault,
                schedules=schedules,
                auto_imports=AutoImports(
                    sources=sources,
                    jobs=jobs,
                    clock=clock,
                    enqueue_job=enqueue_job,
                    remove_version=remove_version,
                ),
            ),
            wrap_handler,
        )
        return cls(
            add_library=add_library,
            add_version=add_version,
            apply_sources=ApplySourcesUseCase(
                reader=SourcesReader(
                    known=known_libraries or _NoKnownLibraries(),
                    sources=sources,
                    jobs=jobs,
                    schedules=schedules,
                ),
                add_library=add_library,
                add_version=add_version,
                update_library_settings=update_library_settings,
                set_auto_sync=SetAutoSyncUseCase(
                    sources=sources, schedules=schedules, switch=switch, access=access
                ),
                disable_auto_sync=DisableAutoSyncUseCase(
                    sources=sources, schedules=schedules, switch=switch, access=access
                ),
                remove_version=remove_version,
                remove_library=remove_library,
                texts=texts or _NoTexts(),
            ),
            cancel_job=CancelJobUseCase(jobs=jobs, clock=clock, access=access),
            check_repository=CheckRepositoryUseCase(remote=remote, library_ids=library_ids),
            disable_auto_sync=DisableAutoSyncUseCase(
                sources=sources, schedules=schedules, switch=switch, access=access
            ),
            disable_webhook=DisableWebhookUseCase(
                sources=sources, webhooks=webhooks or _NoWebhooks()
            ),
            enqueue_job=enqueue_job,
            get_auto_sync=GetAutoSyncUseCase(sources=sources, schedules=schedules, access=access),
            get_job=GetJobUseCase(jobs=jobs, access=access),
            get_library_access=GetLibraryAccessUseCase(
                vault=vault, library_ids=library_ids, access=access
            ),
            get_webhook=GetWebhookUseCase(sources=sources, webhooks=webhooks or _NoWebhooks()),
            list_latest_jobs=ListLatestJobsUseCase(jobs=jobs, access=access),
            list_library_jobs=ListLibraryJobsUseCase(jobs=jobs, access=access),
            list_repository_refs=ListRepositoryRefsUseCase(remote=remote),
            plan_sources=PlanSourcesUseCase(
                reader=SourcesReader(
                    known=known_libraries or _NoKnownLibraries(),
                    sources=sources,
                    jobs=jobs,
                    schedules=schedules,
                )
            ),
            preview_repository=PreviewRepositoryUseCase(remote=remote, tree=tree or _NoTree()),
            queue_embedding=QueueEmbeddingUseCase(queue=embedding),
            receive_webhook=ReceiveWebhookUseCase(
                webhooks=webhooks or _NoWebhooks(),
                deliveries=webhook_deliveries or _NoDeliveries(),
                sources=sources,
                schedules=schedules,
                enqueue_job=enqueue_job,
                clock=clock,
            ),
            recover_jobs=RecoverJobsUseCase(
                jobs=jobs, clock=clock, hooks=recovery_hooks, runner=runner
            ),
            reimport_version=ReimportVersionUseCase(
                remote=remote,
                sources=sources,
                jobs=jobs,
                enqueue_job=enqueue_job,
                vault=vault,
                access=access,
            ),
            remove_library=remove_library,
            remove_version=remove_version,
            run_job=RunJobUseCase(jobs=jobs, clock=clock, handlers=kinds, hooks=recovery_hooks),
            run_next_job=RunNextJobUseCase(jobs=jobs, clock=clock, handlers=kinds),
            run_scheduled_checks=RunScheduledChecksUseCase(
                schedules=schedules,
                sources=sources,
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
                sources=sources, schedules=schedules, switch=switch, access=access
            ),
            set_webhook=SetWebhookUseCase(
                sources=sources, webhooks=webhooks or _NoWebhooks(), clock=clock
            ),
            submit_queued_jobs=SubmitQueuedJobsUseCase(jobs=jobs, runner=runner),
            switch_schedule=SwitchScheduleUseCase(schedules=schedules, switch=switch),
            sync_library=sync_library,
            tag_article=TagArticleUseCase(
                tags=manual_tags or _NoManualTags(),
                index=index,
                locks=tag_locks or TagLocks(),
                access=access,
            ),
            update_library_settings=update_library_settings,
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
    tag_locks: LibraryLocks,
    imported_tags: ImportedTagStore,
    copier: VersionCopier,
    checkpoints: Checkpoints | None = None,
    batch_files: int = DEFAULT_IMPORT_BATCH_FILES,
    guidance: GuidancePolicy | None = None,
    files: RepositoryFiles | None = None,
    converter: MarkupConverter | None = None,
) -> tuple[Mapping[JobKind, JobHandler], Mapping[JobKind, RecoveryHook]]:
    """Return the ``handlers`` and ``recovery_hooks`` that make the module import versions.

    Pass the same ``tag_locks`` to ``IngestionModule.build`` (see ``TagArticleUseCase``).
    The handlers re-process a library after a settings edit too: ``reprocess`` re-imports every
    version; ``rechunk`` re-chunks (and re-tags) the copies ``copier`` makes of what each
    version serves; ``retag`` re-tags them from what ``imported_tags`` has stored.
    ``stored`` lets an import take the files earlier imports stored instead of parsing them.
    ``checkpoints`` makes the import's steps durable (one per ``batch_files`` files parsed and
    chunked); without it an interrupted import starts over. ``guidance`` says which libraries
    keep their ``AGENTS.md`` / ``CLAUDE.md`` files with each version (RET-08), read with
    ``files``; without both none do. ``converter`` writes reStructuredText articles as Markdown;
    without it they are skipped.

    Args:
        gateway: Fetches a commit's files.
        chunker: Cuts articles into chunks.
        sources: Where a library's articles come from.
        versions: Publishes versions into the catalog.
        index: Where chunks are stored and searched.
        vault: Where credentials are kept; None: only public repositories work.
        max_article_bytes: The most bytes one article may have.
        max_import_bytes: The most bytes of text one import may take.
        renames: Tells which files git sees as renamed; None: no renames are followed.
        stored: What earlier imports stored; None: every file is parsed.
        max_image_bytes: The most bytes one image may have.
        max_images_bytes: The most bytes a version's images may add up to.
        tag_locks: Lets tagging and an import's activation take turns.
        imported_tags: The imported tags of what a version serves, for ``retag``.
        copier: Copies what a version serves, for ``rechunk``.
        checkpoints: Makes the import's steps durable.
        batch_files: Files parsed and chunked per durable step.
        guidance: Which libraries keep their instruction files.
        files: Reads the instruction files.
        converter: Writes reStructuredText articles as Markdown.

    Returns:
        The handlers and the recovery hooks, by job kind.
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
        guidance=guidance,
        files=files,
        converter=converter,
    )
    # A cancelled job stops before its next step; each step leaves nothing half done.
    importer = replace(importer, checkpoints=StopOnCancel(inner=checkpoints or _InlineSteps()))
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
    """Return the ``handlers`` entry that makes the module free unused content, in this order.

    Args:
        collectors: What frees what each domain no longer needs, run in order.
        grace_seconds: How long something stays after it became unused.

    Returns:
        The ``collect`` handler.
    """
    return {COLLECT_JOB: CollectGarbageUseCase(collectors=collectors, grace_seconds=grace_seconds)}
