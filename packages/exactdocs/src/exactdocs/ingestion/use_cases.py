"""Ingestion use cases. Each one satisfies a driving port structurally, without inheriting it."""

import asyncio
import codecs
import logging
import os
import stat
import time
import uuid
import weakref
from collections.abc import Awaitable, Callable, Collection, Generator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, AsyncExitStack, contextmanager, suppress
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from typing import BinaryIO, Self

from exactdocs.ingestion.dtos import (
    AddedLibrary,
    AddedVersion,
    AddLibraryCommand,
    AddVersionCommand,
    AutoSyncOut,
    CheckedRepository,
    CheckRepositoryCommand,
    ChunkingIn,
    Context7Out,
    CredentialIn,
    DisableAutoSyncCommand,
    EnqueueJobCommand,
    GetAutoSyncQuery,
    GetJobQuery,
    GetLibraryAccessQuery,
    JobList,
    JobSummary,
    LatestJob,
    LatestJobs,
    LibraryAccess,
    ListLibraryJobsQuery,
    ListRepositoryRefsQuery,
    PreviewRepositoryCommand,
    RefOut,
    ReimportedVersion,
    ReimportVersionCommand,
    RemovalResult,
    RemoveLibraryCommand,
    RemoveVersionCommand,
    RepositoryPreview,
    RepositoryRefs,
    ScheduledChecks,
    SetAutoSyncCommand,
    SyncedLibrary,
    SyncedVersion,
    SyncLibraryCommand,
    TagArticleCommand,
    TaggedArticle,
    TagRuleIn,
    UpdatedLibrarySettings,
    UpdateLibrarySettingsCommand,
)
from exactdocs.ingestion.errors import (
    CheckoutUnreadableError,
    CommitImportedError,
    CredentialsRequiredError,
    ImportInProgressError,
    ImportNotPinnedError,
    ImportTooLargeError,
    InvalidContext7Error,
    JobNotFoundError,
    LibraryIdTakenError,
    NoArticlesError,
    NotAGitRepositoryError,
    NotATagError,
    PreviewBusyError,
    RefDeletedError,
    RepositoryAuthRequiredError,
    RepositoryUnreachableError,
    ReprocessFailedError,
    StoredTextOutdatedError,
    SyncFailedError,
    TagNotMovedError,
    UnknownJobKindError,
    UnknownLibraryError,
    UnknownVersionError,
    VersionExistsError,
    VersionImportingError,
)
from exactdocs.ingestion.models import (
    ACTIVE_JOB_STATES,
    COLLECT_JOB,
    CONTEXT7_FILE,
    CONTEXT7_MAX_BYTES,
    DEFAULT_GRACE_SECONDS,
    DEFAULT_IMPORT_BATCH_FILES,
    DEFAULT_MAX_ARTICLE_BYTES,
    DEFAULT_MAX_IMAGE_BYTES,
    DEFAULT_MAX_IMAGES_BYTES,
    DEFAULT_MAX_IMPORT_BYTES,
    IMPORT_JOB,
    IMPORT_KINDS,
    LIBRARY_KINDS,
    MAX_IMAGES,
    PARSER_VERSION,
    PERMANENT_IMPORT_FAILURES,
    RECHUNK_JOB,
    REFRESH_JOB,
    REPROCESS_JOB,
    RETAG_JOB,
    UNEXPECTED_BACKOFF_CAP,
    UNEXPECTED_ERROR,
    ArticleChunk,
    AutoSync,
    ChunkingConfig,
    Context7Config,
    CopiedVersion,
    Credential,
    FetchedFile,
    FileProblem,
    GitRename,
    ImportedArticle,
    ImportedImage,
    ImportedRef,
    ImportedVersion,
    ImportSource,
    Job,
    JobId,
    JobKind,
    JobState,
    NewLibrary,
    ParsedArticle,
    PathSelection,
    ProblemCode,
    ProposedId,
    ReadmeSummary,
    RefKind,
    RemoteRefs,
    Removed,
    RepositoryUrl,
    ResolvedRef,
    SettingsChange,
    StoredArticleTags,
    SyncErrorCode,
    SyncStatus,
    TagRule,
    VersionOrigin,
    article_tags,
    check_credential_fits,
    compose_renames,
    git_blob_sha,
    is_unordered,
    parse_article,
    parse_context7,
    plan_auto_imports,
    previous_version,
    readme_summary,
    ref_tips,
    resolve_ref,
    sniff_image,
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
    JobProgress,
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
from exactdocs.ingestion.ports.driving import EnqueueJob, RemoveVersion, SyncLibraryFromRefs
from exactdocs_kernel import Clock, DomainError, NotFoundError, paginate

log = logging.getLogger(__name__)

MAX_LISTED_REFS = 1000
MAX_PREVIEW_FILES = 1000


def _credential(sent: CredentialIn | None, repository: RepositoryUrl) -> Credential | None:
    """Convert what a client sent and refuse one the repository's transport cannot carry."""
    if sent is None:
        return None
    credential = sent.to_model()
    check_credential_fits(repository, credential)
    return credential


"""Branches and tags listed each; a repository with more is cut and flagged ``truncated``."""


@dataclass(frozen=True, slots=True)
class EnqueueJobUseCase:
    """Implements ``ports.driving.EnqueueJob``."""

    jobs: JobRepository
    clock: Clock
    handlers: Mapping[JobKind, JobHandler]
    runner: JobRunner

    async def __call__(self, command: EnqueueJobCommand) -> JobSummary:
        """Queue the job and hand it to the runner."""
        kind = JobKind(command.kind)
        if kind not in self.handlers:
            raise UnknownJobKindError(kind)
        job = Job.queued(
            job_id=JobId(str(uuid.uuid7())),  # time-ordered, so IDs sort like creation time
            kind=kind,
            library=command.library,
            version=command.version,
            commit_sha=command.commit_sha,
            ref_kind=command.ref_kind,
            origin=command.origin,
            now=self.clock.now(),
        )
        await self.jobs.add(job)
        await self.runner.submit(job)
        return JobSummary.from_model(job)


@dataclass(frozen=True, slots=True)
class GetJobUseCase:
    """Implements ``ports.driving.GetJob``."""

    jobs: JobRepository

    async def __call__(self, query: GetJobQuery) -> JobSummary:
        """Fetch one job by its ID."""
        job = await self.jobs.get(JobId(query.job_id))
        if job is None:
            raise JobNotFoundError(query.job_id)
        return JobSummary.from_model(job)


@dataclass(frozen=True, slots=True)
class GetLibraryAccessUseCase:
    """Implements ``ports.driving.GetLibraryAccess``."""

    vault: CredentialVault
    library_ids: LibraryIds

    async def __call__(self, query: GetLibraryAccessQuery) -> LibraryAccess:
        """Report a library with a stored credential as private; ``UnknownLibraryError`` if none.

        Fails closed: a public repository that was given a token anyway counts as private, so its
        images are never linked to the host. Library IDs are lower-case.
        """
        library = query.library.lower()
        if not await self.library_ids.is_taken(ProposedId(library)):
            raise UnknownLibraryError(query.library)
        return LibraryAccess(private=await self.vault.has(library))


@dataclass(frozen=True, slots=True)
class ListLibraryJobsUseCase:
    """Implements ``ports.driving.ListLibraryJobs``."""

    jobs: JobRepository

    async def __call__(self, query: ListLibraryJobsQuery) -> JobList:
        """List a page of the library's jobs, newest first."""
        # ponytail: loads all of the library's jobs, then pages in memory; a keyset query in
        # the repository once a library has thousands of jobs.
        jobs = await self.jobs.list_for_library(query.library)
        page = paginate(
            jobs, key=lambda job: job.id, limit=query.limit, cursor=query.cursor, descending=True
        )
        return JobList.from_page(page)


@dataclass(frozen=True, slots=True)
class ListLatestJobsUseCase:
    """Implements ``ports.driving.ListLatestJobs``."""

    jobs: JobRepository

    async def __call__(self) -> LatestJobs:
        """List the newest job of every (library, version), without their skipped files."""
        # ponytail: not paged; one row per imported version, fine until thousands exist.
        # Only imports are syncs; a collection job has no version and is no state of a library.
        latest = await self.jobs.list_latest()
        return LatestJobs(
            jobs=[LatestJob.from_model(job) for job in latest if job.kind in IMPORT_KINDS]
        )


@dataclass(frozen=True, slots=True)
class RecoverJobsUseCase:
    """Implements ``ports.driving.RecoverJobs``."""

    jobs: JobRepository
    clock: Clock
    hooks: Mapping[JobKind, RecoveryHook]
    runner: JobRunner

    async def __call__(self, *, resuming: Collection[str] = ()) -> None:
        """Run the hook of every job left ``running``, then queue it again to run from scratch.

        A kind without a hook has nothing to clean up. A hook that raises fails its job instead
        of keeping the app from starting, because re-running over unclean state would be worse.
        A job in ``resuming`` is the runner's to resume (from its last durable step) and is
        left alone. Every other queued job is then submitted to the runner, oldest first: also
        the ones queued while it was not running.
        """
        # ponytail: assumes one live process runs jobs on the database (the HTTP server; stdio
        # does not). Several would re-queue each other's running jobs: add a lease/heartbeat
        # column and re-queue only expired leases if that ever changes.
        for job in await self.jobs.list_running():
            if job.id in resuming:
                continue
            hook = self.hooks.get(job.kind)
            try:
                if hook is not None:
                    await hook(job)
            except Exception as error:
                log.exception("recovery of job %s (%s) failed", job.id, job.kind)
                await self.jobs.save(
                    job.failed(
                        f"recovery failed: {_describe(error)}",
                        self.clock.now(),
                        code=failure_code(error),
                    )
                )
            else:
                await self.jobs.save(job.requeued())
        await _submit_queued(self.jobs, self.runner, resuming)


@dataclass(frozen=True, slots=True)
class SubmitQueuedJobsUseCase:
    """Implements ``ports.driving.SubmitQueuedJobs``."""

    jobs: JobRepository
    runner: JobRunner

    async def __call__(self) -> None:
        """Submit every queued job, oldest first: one the runner did not take when queued runs."""
        await _submit_queued(self.jobs, self.runner, ())


async def _submit_queued(jobs: JobRepository, runner: JobRunner, skip: Collection[str]) -> None:
    for job in await jobs.list_queued():
        if job.id not in skip:
            await runner.submit(job)


@dataclass(frozen=True, slots=True)
class RunJobUseCase:
    """Implements ``ports.driving.RunJob``."""

    jobs: JobRepository
    clock: Clock
    handlers: Mapping[JobKind, JobHandler]
    hooks: Mapping[JobKind, RecoveryHook]

    async def __call__(self, job_id: str, /) -> None:
        """Start (or resume) the job, run its handler and record how it ended.

        A job found ``running`` was interrupted: its kind's recovery hook undoes what the
        interrupted step left half done (a hook that raises fails the job), then the job starts
        over, its handler replaying the durable steps it had completed.
        """
        job = await self.jobs.get(JobId(job_id))
        if job is None or job.state not in ACTIVE_JOB_STATES:
            return
        if job.state is JobState.RUNNING:
            hook = self.hooks.get(job.kind)
            try:
                if hook is not None:
                    await hook(job)
            except Exception as error:
                log.exception("recovery of job %s (%s) failed", job.id, job.kind)
                failure = f"recovery failed: {_describe(error)}"
                await self.jobs.save(
                    job.failed(failure, self.clock.now(), code=failure_code(error))
                )
                return
            job = job.requeued()  # its progress is rebuilt as the steps are replayed
        started = job.started(self.clock.now())
        await self.jobs.save(started)
        await _run(self.jobs, self.clock, self.handlers, started)


@dataclass(frozen=True, slots=True)
class RunNextJobUseCase:
    """Implements ``ports.driving.RunNextJob``."""

    jobs: JobRepository
    clock: Clock
    handlers: Mapping[JobKind, JobHandler]

    async def __call__(self) -> bool:
        """Claim the next job that may run, run it, and record how it ended."""
        job = await self.jobs.claim_next(self.clock.now())
        if job is None:
            return False
        await _run(self.jobs, self.clock, self.handlers, job)
        return True


async def _run(
    jobs: JobRepository, clock: Clock, handlers: Mapping[JobKind, JobHandler], job: Job
) -> None:
    """Run a started job's handler and store how it ended (raising only if that store fails)."""
    progress = _Progress(jobs, job)
    handler = handlers.get(job.kind)
    code = UNEXPECTED_ERROR
    try:
        if handler is None:
            failure = f"no handler is registered for job kind {job.kind!r}"
        else:
            await handler(job, progress)
            failure = None
    except Exception as error:
        log.exception("job %s (%s) failed", job.id, job.kind)
        failure, code = _describe(error), failure_code(error)
    now = clock.now()
    final = (
        progress.job.succeeded(now)
        if failure is None
        else progress.job.failed(failure, now, code=code)
    )
    try:
        await jobs.save(final)
    except Exception:
        log.exception("could not store the end of job %s (%s)", job.id, job.kind)
        raise


SAVE_EVERY_FILES = 100
SAVE_EVERY_SECONDS = 0.25


@dataclass(slots=True)
class _Progress:
    """Implements ``ports.driven.JobProgress``: keeps the latest job, stores it every so often.

    A job over thousands of files would otherwise rewrite its row (and its problem list) for
    each one. The first and the last report are always stored, and ``RunNextJob`` stores the end.
    """

    jobs: JobRepository
    job: Job
    saved_done: int = 0
    reported: bool = False
    saved_at: float = field(default_factory=time.monotonic)

    async def chunking(self, *, chunked: int, reused: int) -> None:
        self.job = self.job.chunking(chunked=chunked, reused=reused)
        await self._save_if_due()

    async def parsing(self, *, parsed: int, taken: int) -> None:
        self.job = self.job.parsing(parsed=parsed, taken=taken)
        await self._save_if_due()

    async def report(self, *, done: int, total: int) -> None:
        self.job = self.job.progressed(done=done, total=total)
        first, self.reported = not self.reported, True
        if first or done == total or done - self.saved_done >= SAVE_EVERY_FILES:
            await self._save()
        else:
            await self._save_if_due()

    async def problem(self, path: str, code: ProblemCode, reason: str) -> None:
        self.job = self.job.with_problem(path, code, reason)
        await self._save_if_due()

    async def _save_if_due(self) -> None:
        if time.monotonic() - self.saved_at >= SAVE_EVERY_SECONDS:
            await self._save()

    async def _save(self) -> None:
        self.saved_done, self.saved_at = self.job.done, time.monotonic()
        await self.jobs.save(self.job)


def _describe(error: Exception) -> str:
    """Return the text users see: a domain error says what is wrong, else only its type."""
    return str(error) if isinstance(error, DomainError) else f"unexpected {type(error).__name__}"


# Upstream failures, by what users can do about them; the git adapter's finer errors stay the
# HTTP answer of the request that met them (adding a library), a job records the coarse code.
_UPSTREAM_CODES: tuple[tuple[type[DomainError], SyncErrorCode], ...] = (
    (NotAGitRepositoryError, SyncErrorCode.REPO_UNREACHABLE),
    (RepositoryUnreachableError, SyncErrorCode.REPO_UNREACHABLE),
    (RepositoryAuthRequiredError, SyncErrorCode.AUTH_FAILED),
    (CredentialsRequiredError, SyncErrorCode.AUTH_FAILED),
)


def failure_code(error: Exception) -> str:
    """Return the stable code a failed job records for ``error``.

    A repository that cannot be read is ``repo_unreachable``, a refused or unreadable credential
    ``auth_failed`` (callers that sent no credential turn an auth demand into
    ``NotAGitRepositoryError`` first, see ``_anonymous``); any other domain error keeps its own
    code (``no_articles``, ``host_key_changed``...), anything else is ``unexpected``.
    """
    for kind, code in _UPSTREAM_CODES:
        if isinstance(error, kind):
            return code
    return error.code if isinstance(error, DomainError) else UNEXPECTED_ERROR


def _anonymous(error: DomainError, credential: Credential | None) -> DomainError:
    """Return what ``error`` means for a library read with ``credential``.

    A server that wants a login when none was sent is hiding the repository: it was deleted or
    made private (GitHub answers a missing repository with 401, never 404). Only when a token or
    key was sent and refused is it a credential problem.
    """
    if credential is None and isinstance(error, RepositoryAuthRequiredError):
        return NotAGitRepositoryError()
    return error


@dataclass(frozen=True, slots=True)
class CheckRepositoryUseCase:
    """Implements ``ports.driving.CheckRepository``."""

    remote: GitRemote
    library_ids: LibraryIds

    async def __call__(self, command: CheckRepositoryCommand) -> CheckedRepository:
        """Parse the URL, refuse a taken ID, then ask the remote for its default branch."""
        repository = RepositoryUrl.parse(command.url)
        if await self.library_ids.is_taken(repository.library_id):
            raise LibraryIdTakenError(repository.library_id)
        credential = _credential(command.credential, repository)
        refs = await self.remote.list_refs(repository, "HEAD", credential=credential)
        return CheckedRepository(
            host=repository.host_kind,
            library_id=repository.library_id,
            default_branch=refs.default_branch,
            host_key_fingerprint=await self.remote.host_key_fingerprint(repository),
        )


@dataclass(frozen=True, slots=True)
class ListRepositoryRefsUseCase:
    """Implements ``ports.driving.ListRepositoryRefs``."""

    remote: GitRemote

    async def __call__(self, query: ListRepositoryRefsQuery) -> RepositoryRefs:
        """Parse the URL and list what the remote advertises, at most ``MAX_LISTED_REFS`` each.

        A credential is only used for this one listing: nothing is stored.
        """
        repository = RepositoryUrl.parse(query.url)
        credential = _credential(query.credential, repository)
        refs = await self.remote.list_refs(repository, credential=credential)
        tips = ref_tips(refs)
        branches = [
            RefOut(name=t.name, commit_sha=t.commit_sha) for t in tips if t.kind is RefKind.BRANCH
        ]
        tags = [RefOut(name=t.name, commit_sha=t.commit_sha) for t in tips if t.kind is RefKind.TAG]
        return RepositoryRefs(
            default_branch=refs.default_branch,
            branches=branches[:MAX_LISTED_REFS],
            tags=tags[:MAX_LISTED_REFS],
            truncated=max(len(branches), len(tags)) > MAX_LISTED_REFS,
        )


@dataclass(frozen=True, slots=True)
class PreviewRepositoryUseCase:
    """Implements ``ports.driving.PreviewRepository``."""

    remote: GitRemote
    tree: RepositoryTree

    async def __call__(self, command: PreviewRepositoryCommand) -> RepositoryPreview:
        """Validate, pin the ref, list the commit's tree and apply the selection to it.

        The same ``PathSelection.selects`` the import uses decides, so the preview and the
        import agree (except for files the import then skips as unreadable or too big). The
        root ``context7.json`` is read too (that one blob, under a preview slot like the
        listing): without paths its selection is the one applied, as adding the library would,
        and the file is returned for the form.
        """
        repository = RepositoryUrl.parse(command.url)
        credential = _credential(command.credential, repository)
        selection = PathSelection.of(command.include_paths, command.exclude_paths)
        refs = await self.remote.list_refs(repository, credential=credential)
        resolved = resolve_ref(refs, command.ref)
        paths = await self.tree.list_files(
            repository,
            resolved.commit_sha,
            refs=_full_refs(resolved.kind, resolved.name),
            credential=credential,
        )
        context7 = await _fetch_context7(self.tree, repository, resolved, credential)
        selection = _prefilled(selection, context7)
        matching = sorted(path for path in paths if selection.selects(path))
        return RepositoryPreview(
            ref=resolved.name,
            ref_kind=resolved.kind,
            commit_sha=resolved.commit_sha,
            files=matching[:MAX_PREVIEW_FILES],
            total=len(matching),
            truncated=len(matching) > MAX_PREVIEW_FILES,
            include_paths=list(selection.include),
            exclude_paths=list(selection.exclude),
            context7=_context7_out(context7),
            context7_warning=context7.warning,
        )


def _prefilled(selection: PathSelection, context7: _Context7Read) -> PathSelection:
    """Keep the paths a user sent; without any, take those of ``context7.json`` (LIB-06)."""
    if selection.include or selection.exclude or context7.config is None:
        return selection
    return context7.config.selection or selection


def _context7_out(context7: _Context7Read) -> Context7Out | None:
    return None if context7.config is None else Context7Out.from_model(context7.config)


@dataclass(frozen=True, slots=True)
class AddLibraryUseCase:
    """Implements ``ports.driving.AddLibrary``."""

    remote: GitRemote
    library_ids: LibraryIds
    libraries: NewLibraries
    enqueue_job: EnqueueJob
    vault: CredentialVault
    tree: RepositoryTree | None = None

    async def __call__(self, command: AddLibraryCommand) -> AddedLibrary:
        """Check everything that can be checked first, then store the library and queue its import.

        Sent without paths, the library takes those of the root ``context7.json`` at the pinned
        commit (LIB-06); paths a user sends win. Without paths, ``PreviewBusyError`` (429) when
        the file cannot be read because every preview slot stays busy, before anything is
        stored: changing the paths later re-processes every version, so guessing "every file"
        is no harmless default. The file's title, description and rules are applied by the
        import, which reads it again with the README.
        The credential, if any, is stored (encrypted) before the import is queued, because the
        import reads it. If that or queueing fails, the new library and its credential are
        removed again, so a retry is not met with a 409.
        """
        repository = RepositoryUrl.parse(command.url)
        credential = _credential(command.credential, repository)
        selection = PathSelection.of(command.include_paths, command.exclude_paths)
        tag_rules = TagRule.many([(r.pattern, r.tag) for r in command.tag_rules])
        library_id = ProposedId(command.library_id or repository.library_id)
        if await self.library_ids.is_taken(library_id):
            raise LibraryIdTakenError(library_id)
        refs = await self.remote.list_refs(repository, credential=credential)
        resolved = resolve_ref(refs, command.ref)
        # Without paths the file decides them for good: a busy slot is a 429, not "every file".
        context7 = await _fetch_context7(
            self.tree,
            repository,
            resolved,
            credential,
            busy_raises=not (selection.include or selection.exclude),
        )
        selection = _prefilled(selection, context7)
        created = await self.libraries.add(
            NewLibrary(
                library_id=library_id,
                title=library_id.rsplit("/", 1)[-1],
                source_url=repository.url,
                host=repository.host_kind,
                default_branch=refs.default_branch,
                selection=selection,
                tag_rules=tag_rules,
            )
        )
        try:
            # Whatever an earlier library of this ID left behind must not be inherited.
            if credential is None:
                await self.vault.delete(created)
            else:
                await self.vault.save(created, repository.credential_scope, credential)
            job = await _enqueue_import(self.enqueue_job, created, resolved)
        except BaseException:
            for undo in (self.vault.delete, self.libraries.discard):
                try:
                    await undo(created)
                except Exception:
                    log.exception(
                        "could not remove library %s after its import failed to queue", created
                    )
            raise
        return AddedLibrary.of(created, resolved, job).model_copy(
            update={
                "include_paths": list(selection.include),
                "exclude_paths": list(selection.exclude),
                "context7": _context7_out(context7),
                "context7_warning": context7.warning,
            }
        )


async def _enqueue_import(
    enqueue_job: EnqueueJob,
    library: str,
    resolved: ResolvedRef,
    origin: VersionOrigin = VersionOrigin.MANUAL,
) -> JobSummary:
    """Queue the import of a ref already pinned to its commit."""
    return await enqueue_job(
        EnqueueJobCommand(
            kind=IMPORT_JOB,
            library=library,
            version=resolved.name,
            commit_sha=resolved.commit_sha,
            ref_kind=resolved.kind,
            origin=origin,
        )
    )


@dataclass(frozen=True, slots=True)
class AddVersionUseCase:
    """Implements ``ports.driving.AddVersion``."""

    remote: GitRemote
    sources: LibrarySources
    jobs: JobRepository
    enqueue_job: EnqueueJob
    vault: CredentialVault

    async def __call__(self, command: AddVersionCommand) -> AddedVersion:
        """Pin the ref like ``AddLibrary`` does and queue the import with the library's settings.

        The import job reads the library's selection and tag rules when it runs, so the version
        is built exactly like the ones before it. Refused (nothing queued): a ref the library
        already has (re-syncing is a different action), a ref whose import is still queued or
        running, and a commit SHA that is already a version under another ref (a tag and a
        branch at one commit stay two versions: the branch moves on).
        The in-progress check is made again, atomically, by the job repository when the job is
        stored, so two simultaneous requests cannot both queue an import of one ref.
        """
        library = command.library
        source = await self.sources.get(library)
        existing = {v.ref: v for v in await self.sources.imported_versions(library)}
        sent = _credential(command.credential, source.url)
        scope = source.url.credential_scope
        credential = sent or await self.vault.load(library, scope)
        refs = await self.remote.list_refs(source.url, credential=credential)
        resolved = resolve_ref(refs, command.ref)
        if resolved.name in existing:
            raise VersionExistsError(library, resolved.name)
        if resolved.kind is RefKind.COMMIT:
            for ref, version in existing.items():
                if version.commit_sha == resolved.commit_sha:
                    raise CommitImportedError(library, version.commit_sha, ref)
        if resolved.name in _busy_refs(await self.jobs.list_for_library(library)):
            raise VersionImportingError(library, resolved.name)
        if sent is not None:
            # Before queueing, because the job reads it; the ref was found with it just now.
            await self.vault.save(library, scope, sent)
        job = await _enqueue_import(self.enqueue_job, library, resolved)
        return AddedVersion.of(library, resolved, job)


def _busy_refs(jobs: Sequence[Job]) -> dict[str, Job]:
    """Return the library's unfinished import jobs by ref."""
    return {
        job.version: job
        for job in jobs
        if job.kind in IMPORT_KINDS and job.state in ACTIVE_JOB_STATES and job.version
    }


_CHECKED_KINDS = frozenset({RefKind.BRANCH, RefKind.TAG})
"""What a sync asks the remote about: a commit names itself and cannot move or go."""


@dataclass(frozen=True, slots=True)
class SyncLibraryUseCase:
    """Implements ``ports.driving.SyncLibrary``."""

    remote: GitRemote
    sources: LibrarySources
    jobs: JobRepository
    clock: Clock
    enqueue_job: EnqueueJob
    vault: CredentialVault

    async def __call__(
        self, command: SyncLibraryCommand, *, refs: RemoteRefs | None = None
    ) -> SyncedLibrary:
        """Ask the remote where each branch and tag is now, queue an import for moved branches.

        ``refs`` is what the remote advertised a moment ago (the scheduled check listed it for
        the tags): the remote is not asked again.

        The import is the one of adding a version: pinned to the new commit, it fetches it,
        reuses the chunks of every unchanged blob and activates the new manifest in place of the
        old one (the version keeps its ID). A commit is never checked; a tag is checked but never
        re-imported: one that still names its commit is ``pinned``, one that now names another
        is ``failed`` with ``tag_moved``. A branch whose import is queued or running is reported
        as importing and left alone (the job repository refuses a second one atomically);
        ``VersionImportingError`` is raised only when that left nothing queued.
        If the remote cannot be read (``repo_unreachable``, ``auth_failed``), or a branch or tag
        is gone (``ref_deleted``), the failure is recorded on a failed job of that version (once
        per distinct reason), so users see it next to the version that keeps serving. When a
        version that last failed is fine again, a succeeded job with no work says so. A version
        removed while this runs may still get such a record.
        """
        library = command.library
        source = await self.sources.get(library)
        versions = await self.sources.imported_versions(library)
        checked = [v for v in versions if v.kind in _CHECKED_KINDS]
        jobs = await self.jobs.list_for_library(library)  # newest first
        busy = _busy_refs(jobs)
        newest: dict[str, Job] = {}
        for job in jobs:
            if job.version:
                newest.setdefault(job.version, job)
        tips: dict[tuple[RefKind, str], str] = {}
        if checked:
            credential: Credential | None = None
            try:
                # An unreadable or other-host credential is recorded like any failure to read.
                if refs is None:
                    credential = await self.vault.load(library, source.url.credential_scope)
                    refs = await self.remote.list_refs(source.url, credential=credential)
            except DomainError as raised:
                error = _anonymous(raised, credential)
                code = failure_code(error)
                recorded = [
                    (await self._failed(library, v, _describe(error), code, newest.get(v.ref))).id
                    for v in checked
                    if v.ref not in busy
                ]
                raise SyncFailedError(error, recorded, code) from raised
            tips = {(t.kind, t.name): t.commit_sha for t in ref_tips(refs)}
        # The busy check is repeated, atomically, by ``enqueue_job`` (the repository).
        synced = [await self._sync(library, v, tips, busy, newest) for v in versions]
        importing = [v for v in synced if v.status is SyncStatus.IMPORTING]
        if importing and not any(v.status is SyncStatus.QUEUED for v in synced):
            raise VersionImportingError(library, importing[0].ref)
        return SyncedLibrary(library_id=library, versions=synced)

    async def _sync(
        self,
        library: str,
        current: ImportedRef,
        tips: Mapping[tuple[RefKind, str], str],
        busy: Mapping[str, Job],
        newest: Mapping[str, Job],
    ) -> SyncedVersion:
        def outcome(
            status: SyncStatus, commit_sha: str, job_id: str | None = None
        ) -> SyncedVersion:
            return SyncedVersion(
                ref=current.ref,
                ref_kind=current.kind,
                status=status,
                previous_commit_sha=current.commit_sha,
                commit_sha=commit_sha,
                job_id=job_id,
            )

        def failure(job: Job) -> SyncedVersion:
            return outcome(SyncStatus.FAILED, current.commit_sha, job.id).model_copy(
                update={"error_code": job.error_code, "error": job.error}
            )

        if current.kind not in _CHECKED_KINDS:
            return outcome(SyncStatus.PINNED, current.commit_sha)
        if current.ref in busy:
            return outcome(SyncStatus.IMPORTING, current.commit_sha, busy[current.ref].id)
        last = newest.get(current.ref)
        tip = tips.get((current.kind, current.ref))
        if tip is None:
            what = "branch" if current.kind is RefKind.BRANCH else "tag"
            reason = f"the {what} {current.ref!r} no longer exists in the repository"
            failed = await self._failed(library, current, reason, SyncErrorCode.REF_DELETED, last)
            return failure(failed)
        if tip == current.commit_sha:
            noop = await self._confirm(library, current, tip, last)
            kept = SyncStatus.UP_TO_DATE if current.kind is RefKind.BRANCH else SyncStatus.PINNED
            return outcome(kept, tip, noop)
        if current.kind is RefKind.TAG:
            # Never re-imported: a moved tag is a surprise upstream, not an update to follow.
            reason = (
                f"the tag {current.ref!r} now points at commit {tip}, not at {current.commit_sha} "
                "which this version serves; it is not re-imported until you confirm the re-import "
                "of the version at the new commit"
            )
            failed = await self._failed(library, current, reason, SyncErrorCode.TAG_MOVED, last)
            return failure(failed)
        return await self._moved(library, current, tip, outcome)

    async def _confirm(
        self, library: str, current: ImportedRef, tip: str, last: Job | None
    ) -> str | None:
        """Record a succeeded no-op job when the version last failed: its error is over."""
        if last is None or last.state is not JobState.FAILED:
            return None
        now = self.clock.now()
        noop = self._job(library, current, now, commit_sha=tip).started(now).succeeded(now)
        await self.jobs.add(noop)
        return noop.id

    async def _moved(
        self,
        library: str,
        current: ImportedRef,
        tip: str,
        outcome: Callable[[SyncStatus, str, str | None], SyncedVersion],
    ) -> SyncedVersion:
        try:
            job = await self.enqueue_job(
                EnqueueJobCommand(
                    kind=REFRESH_JOB,  # fails, not resurrects, if the version is removed meanwhile
                    library=library,
                    version=current.ref,
                    commit_sha=tip,
                    ref_kind=RefKind.BRANCH,
                )
            )
        except VersionImportingError:  # another request queued it since the check above
            return outcome(SyncStatus.IMPORTING, current.commit_sha, None)
        except Exception:
            # The imports queued for other branches stay queued; this one is reported, not lost.
            log.exception("could not queue the sync of %s in %s", current.ref, library)
            return outcome(SyncStatus.FAILED, current.commit_sha, None).model_copy(
                update={"error_code": UNEXPECTED_ERROR, "error": "the import could not be queued"}
            )
        return outcome(SyncStatus.QUEUED, tip, job.id)

    def _job(
        self, library: str, current: ImportedRef, now: datetime, *, commit_sha: str | None = None
    ) -> Job:
        return Job.queued(
            job_id=JobId(str(uuid.uuid7())),
            kind=REFRESH_JOB,
            library=library,
            version=current.ref,
            commit_sha=commit_sha,
            ref_kind=current.kind,
            now=now,
        )

    async def _failed(
        self, library: str, current: ImportedRef, reason: str, code: str, last: Job | None
    ) -> Job:
        """Record a failed job, unless the version's newest job already says the same."""
        if (
            last is not None
            and last.state is JobState.FAILED
            and (last.error, last.error_code) == (reason, code)
        ):
            return last
        now = self.clock.now()
        job = self._job(library, current, now).failed(reason, now, code=code)
        await self.jobs.add(job)
        return job


class _NoCheckpoints:
    """The default ``Checkpoints``: every step runs, nothing survives a crash."""

    async def step[T](self, name: str, run: Callable[[], Awaitable[T]], /) -> T:
        del name
        return await run()


@dataclass(frozen=True, slots=True)
class ReimportVersionUseCase:
    """Implements ``ports.driving.ReimportVersion``."""

    remote: GitRemote
    sources: LibrarySources
    jobs: JobRepository
    enqueue_job: EnqueueJob
    vault: CredentialVault

    async def __call__(self, command: ReimportVersionCommand) -> ReimportedVersion:
        """Ask the remote where the tag is now and queue its import there, as a sync would a branch.

        The import is a ``refresh``: pinned to the new commit, it reuses the chunks of every
        unchanged blob and activates the new manifest in place of the old one, so the version
        keeps its ID and serves the old commit until then; it fails, not resurrects, if the
        version is removed meanwhile. Its job becomes the version's newest, so the ``tag_moved``
        failure a sync recorded is no longer the version's state. The tag is checked again here,
        not taken from that record: only a tag that names another commit now is re-imported.
        """
        library = command.library
        source = await self.sources.get(library)  # an unknown library is not found
        versions = {v.ref: v for v in await self.sources.imported_versions(library)}
        current = versions.get(command.ref)
        if current is None:
            raise UnknownVersionError(library, command.ref)
        if current.kind is not RefKind.TAG:
            raise NotATagError(current.ref, current.kind.value)
        if current.ref in _busy_refs(await self.jobs.list_for_library(library)):
            raise VersionImportingError(library, current.ref)
        credential: Credential | None = None
        try:
            credential = await self.vault.load(library, source.url.credential_scope)
            refs = await self.remote.list_refs(source.url, credential=credential)
        except DomainError as raised:
            raise _anonymous(raised, credential) from raised
        tips = {(t.kind, t.name): t.commit_sha for t in ref_tips(refs)}
        tip = tips.get((RefKind.TAG, current.ref))
        if tip is None:
            raise RefDeletedError(current.ref)
        if tip == current.commit_sha:
            raise TagNotMovedError(library, current.ref, tip)
        # The busy check is repeated, atomically, by ``enqueue_job`` (the repository).
        job = await self.enqueue_job(
            EnqueueJobCommand(
                kind=REFRESH_JOB,
                library=library,
                version=current.ref,
                commit_sha=tip,
                ref_kind=RefKind.TAG,
            )
        )
        return ReimportedVersion(
            library_id=library,
            ref=current.ref,
            ref_kind=RefKind.TAG,
            previous_commit_sha=current.commit_sha,
            commit_sha=tip,
            job_id=job.id,
        )


@dataclass(frozen=True, slots=True)
class TagLocks:
    """One ``asyncio.Lock`` per library: re-tagging (see ``TagArticleUseCase``), settings edits.

    For re-tagging, create one and give the same object to the importer and to tagging; another
    purpose takes another object. Libraries do not wait on each other; a lock nobody holds or
    waits for is dropped.
    """

    _locks: weakref.WeakValueDictionary[str, asyncio.Lock] = field(
        default_factory=weakref.WeakValueDictionary
    )

    def of(self, library: str) -> asyncio.Lock:
        """Return the lock of ``library`` (`/owner/repo`, any letter case)."""
        key = library.lower()
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()
        return lock


def _settings_change(
    current: ImportSource,
    selection: PathSelection,
    tag_rules: Sequence[TagRule],
    chunking: ChunkingConfig,
) -> SettingsChange | None:
    """Say what new settings ask of the versions: re-import, re-chunk, re-tag, or nothing."""
    if selection != current.selection:
        return SettingsChange.PATHS
    if chunking != current.chunking:
        return SettingsChange.CHUNKING
    if tuple(tag_rules) != tuple(current.tag_rules):
        return SettingsChange.TAGS
    return None


_CHANGE_JOBS = {
    SettingsChange.PATHS: REPROCESS_JOB,
    SettingsChange.CHUNKING: RECHUNK_JOB,
    SettingsChange.TAGS: RETAG_JOB,
}
_JOB_CHANGES = {kind: change for change, kind in _CHANGE_JOBS.items()}


def _unhealed(jobs: Sequence[Job]) -> SettingsChange | None:
    """Return the widest re-processing that failed and was not redone since (newest first).

    A failed job is redone by any later job of the same or a greater reach that succeeded, or
    is still queued or running (it reads the settings when it runs): a failed ``reprocess``
    stays unhealed after a ``retag`` or a ``rechunk``, which do not re-import.
    """
    covered = 0
    worst: SettingsChange | None = None
    for job in jobs:
        change = _JOB_CHANGES.get(job.kind)
        if change is None:
            continue
        if job.state is JobState.FAILED:
            if change.reach > covered and (worst is None or change.reach > worst.reach):
                worst = change
        else:
            covered = max(covered, change.reach)
    return worst


def _wider(one: SettingsChange, other: SettingsChange | None) -> SettingsChange:
    return one if other is None or one.reach >= other.reach else other


@dataclass(frozen=True, slots=True)
class UpdateLibrarySettingsUseCase:
    """Implements ``ports.driving.UpdateLibrarySettings``."""

    sources: LibrarySources
    settings: LibrarySettingsStore
    jobs: JobRepository
    enqueue_job: EnqueueJob
    locks: TagLocks = field(default_factory=TagLocks)
    """Its own per-library locks (not the tag locks): edits of one library take turns."""

    async def __call__(self, command: UpdateLibrarySettingsCommand) -> UpdatedLibrarySettings:
        """Validate, store, then queue the one job that re-processes every version.

        The job reads the settings and the versions when it runs, and a library's jobs run one
        at a time in queue order: an import queued or running before the edit is re-processed
        after it, one queued after it reads the new settings itself. A queued job that does at
        least what is needed (``reprocess`` > ``rechunk`` > ``retag``) is reused. If the job
        cannot be queued the old settings are put back, so a retry is not "unchanged".
        Settings equal to the stored ones queue the library's last failed re-processing again
        (``_unhealed``), so a retry with the same body re-runs it; else nothing. A smaller edit
        while a wider re-processing is unhealed queues the wider one: a ``retag`` would not
        re-import the version that failed, and would hide the failure.
        Edits of one library take turns (``locks``): read, compare, store, queue and roll back
        are one step against another edit (one process serves the API).
        """
        library = command.library.lower()
        selection = PathSelection.of(command.include_paths, command.exclude_paths)
        tag_rules = TagRule.many([(r.pattern, r.tag) for r in command.tag_rules])
        wanted = command.chunking
        sent = (
            None
            if wanted is None
            else ChunkingConfig(
                split_depth=wanted.split_level,
                min_chars=wanted.min_chars,
                max_chars=wanted.max_chars,
                chunker=wanted.chunker,
            )
        )
        async with self.locks.of(library):
            change, chunking, refs, job_id = await self._update(library, selection, tag_rules, sent)
        return UpdatedLibrarySettings(
            library_id=library,
            include_paths=list(selection.include),
            exclude_paths=list(selection.exclude),
            tag_rules=[TagRuleIn(pattern=r.pattern, tag=r.tag) for r in tag_rules],
            chunking=ChunkingIn.of(chunking),
            reprocess=change,
            job_id=job_id,
            versions=refs,
        )

    async def _update(
        self,
        library: str,
        selection: PathSelection,
        tag_rules: Sequence[TagRule],
        sent: ChunkingConfig | None,
    ) -> tuple[SettingsChange | None, ChunkingConfig, list[str], str | None]:
        """Compare, store and queue; chunking left out (``None``) keeps the stored one."""
        current = await self.sources.get(library)
        chunking = current.chunking if sent is None else sent
        change = _settings_change(current, selection, tag_rules, chunking)
        if change is None:
            change, refs, job_id = await self._retry(library)
            return change, chunking, refs, job_id
        await self.settings.save(library, selection, tag_rules, chunking)
        # BaseException on purpose: a cancelled request must put the old settings back too.
        try:
            refs = [v.ref for v in await self.sources.imported_versions(library)]
            jobs = await self.jobs.list_for_library(library)
            change = _wider(change, _unhealed(jobs))  # a smaller job would hide that failure
            job_id = await self._queue(library, change, jobs) if refs or _busy_refs(jobs) else None
        except BaseException:
            try:
                await self.settings.save(
                    library, current.selection, current.tag_rules, current.chunking
                )
            except Exception:
                log.exception("could not restore the settings of %s", library)
            raise
        return change, chunking, refs, job_id

    async def _retry(self, library: str) -> tuple[SettingsChange | None, list[str], str | None]:
        """Queue the library's widest failed re-processing not redone since; else do nothing."""
        jobs = await self.jobs.list_for_library(library)  # newest first
        change = _unhealed(jobs)
        if change is None:
            return None, [], None
        refs = [v.ref for v in await self.sources.imported_versions(library)]
        return change, refs, await self._queue(library, change, jobs)

    async def _queue(self, library: str, change: SettingsChange, jobs: Sequence[Job]) -> str:
        reusable = {kind for kind, done in _JOB_CHANGES.items() if done.reach >= change.reach}
        for job in jobs:
            if job.kind in reusable and job.state is JobState.QUEUED:
                return job.id
        queued = await self.enqueue_job(
            EnqueueJobCommand(kind=_CHANGE_JOBS[change], library=library)
        )
        return queued.id


@dataclass(frozen=True, slots=True)
class _VersionOutcome:
    """What re-processing one version did: the result of its durable step (plain data)."""

    chunked: int = 0
    reused: int = 0
    parsed: int = 0
    taken: int = 0
    problems: tuple[FileProblem, ...] = ()
    failure: tuple[str, str] | None = None
    """``(code, reason)`` when the version could not be re-processed and kept what it had."""

    def plus(self, other: Self) -> Self:
        """Return the counters of both added up (problems and failure are left out)."""
        return replace(
            self,
            chunked=self.chunked + other.chunked,
            reused=self.reused + other.reused,
            parsed=self.parsed + other.parsed,
            taken=self.taken + other.taken,
            problems=(),
            failure=None,
        )


@dataclass(slots=True)
class _OneVersion:
    """Implements ``ports.driven.JobProgress`` for one version's re-import, inside its step.

    The job counts versions, not files (as ``retag`` does), so a file report is not passed on.
    Chunk and parse counters go on from the versions before, live. Problems are kept for the step's
    result and reported after it, so a resumed job reports them again from the result.
    """

    progress: JobProgress
    ref: str
    before: _VersionOutcome
    """The counters of the versions before this one."""
    chunked: int = 0
    reused: int = 0
    parsed: int = 0
    taken: int = 0
    problems: list[FileProblem] = field(default_factory=list)

    async def report(self, *, done: int, total: int) -> None:
        del done, total

    async def problem(self, path: str, code: ProblemCode, reason: str) -> None:
        self.problems.append(FileProblem(path, code, f"{self.ref}: {reason}"))

    async def chunking(self, *, chunked: int, reused: int) -> None:
        self.chunked, self.reused = chunked, reused
        await self.progress.chunking(
            chunked=self.before.chunked + chunked, reused=self.before.reused + reused
        )

    async def parsing(self, *, parsed: int, taken: int) -> None:
        self.parsed, self.taken = parsed, taken
        await self.progress.parsing(
            parsed=self.before.parsed + parsed, taken=self.before.taken + taken
        )

    def outcome(self, failure: tuple[str, str] | None = None) -> _VersionOutcome:
        return _VersionOutcome(
            chunked=self.chunked,
            reused=self.reused,
            parsed=self.parsed,
            taken=self.taken,
            problems=tuple(self.problems),
            failure=failure,
        )


async def _versions(sources: LibrarySources, library: str) -> tuple[ImportedRef, ...]:
    return tuple(await sources.imported_versions(library))


@dataclass(frozen=True, slots=True)
class ReprocessLibraryUseCase:
    """Implements ``ports.driven.JobHandler`` for ``REPROCESS_JOB``.

    Re-imports each version of the library at the commit it serves (``done`` / ``total`` count
    versions), with the library's settings
    as they are now: the refresh importer fetches the commit, reuses the chunks of every blob
    chunked before and activates the new manifest in place of the old one, so each version
    switches at once. A version that fails keeps what it served and the others go on; the job
    then fails with every failure (``ReprocessFailedError``).

    Durable steps (``checkpoints``): the list of versions, then one step per version, in that
    order, so a resumed job takes the same versions in the same order and skips those it had
    finished (or failed). A version's re-import is one step, not the importer's own steps: the
    importer reads the library and its credential before its first step, so a version that
    failed there and succeeds on resume would take steps another version had recorded. A
    version killed halfway starts over (the recovery hook discards its pending manifest).
    ``importer`` must therefore not record steps of its own (give it no checkpoints).
    """

    sources: LibrarySources
    importer: JobHandler
    checkpoints: Checkpoints = field(default_factory=_NoCheckpoints)

    async def __call__(self, job: Job, progress: JobProgress, /) -> None:
        """Re-import every version; raising fails the job."""
        step = self.checkpoints.step
        versions = await step("list the versions", partial(_versions, self.sources, job.library))
        await progress.report(done=0, total=len(versions))
        total = _VersionOutcome()
        failures: list[tuple[str, str, str]] = []
        for done, current in enumerate(versions, 1):
            tracker = _OneVersion(progress, current.ref, total)
            outcome = await step(
                f"re-import {current.ref}", partial(self._one, job, current, tracker)
            )
            total = total.plus(outcome)
            for problem in outcome.problems:
                await progress.problem(problem.path, problem.code, problem.reason)
            await progress.report(done=done, total=len(versions))
            await progress.chunking(chunked=total.chunked, reused=total.reused)
            await progress.parsing(parsed=total.parsed, taken=total.taken)
            if outcome.failure is not None:
                failures.append((current.ref, *outcome.failure))
        if failures:
            raise ReprocessFailedError(failures)

    async def _one(self, job: Job, current: ImportedRef, tracker: _OneVersion) -> _VersionOutcome:
        return await _reimport(self.importer, job, current, tracker)


async def _reimport(
    importer: JobHandler, job: Job, current: ImportedRef, tracker: _OneVersion
) -> _VersionOutcome:
    """Re-import one version at the commit it serves; a failure is the outcome, not raised."""
    one = replace(
        job,
        kind=REFRESH_JOB,
        version=current.ref,
        commit_sha=current.commit_sha,  # where it is, never where its branch is now
        ref_kind=current.kind,
    )
    try:
        await importer(one, tracker)
    except Exception as error:
        log.warning("re-processing %s %s failed", job.library, current.ref, exc_info=True)
        return tracker.outcome((failure_code(error), _describe(error)))
    return tracker.outcome()


@dataclass(frozen=True, slots=True)
class RetagLibraryUseCase:
    """Implements ``ports.driven.JobHandler`` for ``RETAG_JOB``: nothing is fetched or chunked.

    Each version's stored articles get the imported tags the library's tag rules give them now
    (with their stored front matter), in one catalog transaction per version, then their chunks
    the same tags: the catalog switches at once, search follows right after. Under the library's
    tag lock, like manual tagging, so the two never interleave. Every article's tags are sent
    to both every time (each side writes only what differs), so a rerun after a crash or a
    failure between the two writes brings the chunks in line. A version that fails keeps what
    it had and the others go on; the job then fails with every failure.

    Durable steps (``checkpoints``): the list of versions, then one per version, so a resumed
    job does not re-tag the versions it had finished. A version killed halfway is re-tagged
    again, which is safe for the reason above.
    """

    sources: LibrarySources
    tags: ImportedTagStore
    index: ChunkIndex
    tag_locks: TagLocks
    checkpoints: Checkpoints = field(default_factory=_NoCheckpoints)

    async def __call__(self, job: Job, progress: JobProgress, /) -> None:
        """Re-tag every version; raising fails the job."""
        step = self.checkpoints.step
        versions = await step("list the versions", partial(_versions, self.sources, job.library))
        await progress.report(done=0, total=len(versions))
        reused = 0
        failures: list[tuple[str, str, str]] = []
        for done, current in enumerate(versions, 1):
            outcome = await step(
                f"re-tag {current.ref}", partial(self._one, job.library, current.ref)
            )
            reused += outcome.reused
            if outcome.failure is not None:
                failures.append((current.ref, *outcome.failure))
            await progress.chunking(chunked=0, reused=reused)
            await progress.report(done=done, total=len(versions))
        if failures:
            raise ReprocessFailedError(failures)

    async def _one(self, library: str, ref: str) -> _VersionOutcome:
        try:
            return _VersionOutcome(reused=await self._retag(library, ref))
        except Exception as error:
            log.warning("re-tagging %s %s failed", library, ref, exc_info=True)
            return _VersionOutcome(failure=(failure_code(error), _describe(error)))

    async def _retag(self, library: str, ref: str) -> int:
        """Re-tag one version with the rules as they are now; return its stored articles."""
        rules = (await self.sources.get(library)).tag_rules
        async with self.tag_locks.of(library):
            stored = await self.tags.stored_tags(library, ref)
            if stored is None or not stored.articles:
                return 0
            wanted = {article.path: article.retagged(rules) for article in stored.articles}
            everything = await self.tags.set_imported_tags(stored.manifest_id, wanted)
            if everything:
                await self.index.retag(stored.manifest_id, everything)
            return len(stored.articles)


@dataclass(frozen=True, slots=True)
class RechunkLibraryUseCase:
    """Implements ``ports.driven.JobHandler`` for ``RECHUNK_JOB``: nothing is fetched.

    Each version's active manifest is copied into a pending one (same articles, images and
    renames), its articles get the imported tags the tag rules give now, and they are cut with
    the library's chunking as it is now, from the stored text: a blob already chunked with that
    config takes its stored chunks. The copy is indexed and activated like an import (manual
    tags last, under the tag lock), so each version switches at once and serves its old chunks
    until then. A version whose text was stored by another parser version is re-imported at its
    commit instead (``importer``, a refresh importer without steps of its own): its text is not
    what the parser gives now, and chunks keyed with the current parser must not be cut from
    it. A version that fails keeps what it served and the others go on; the job then fails with
    every failure. ``done`` / ``total`` count versions.

    Durable steps (``checkpoints``): the list of versions, then one per version, as for
    ``ReprocessLibraryUseCase``. A version killed halfway starts over (the recovery hook
    discards its pending copy).
    """

    sources: LibrarySources
    copier: VersionCopier
    chunker: Chunker
    tags: ImportedTagStore
    versions: VersionPublisher
    index: ChunkIndex
    tag_locks: TagLocks
    importer: JobHandler
    checkpoints: Checkpoints = field(default_factory=_NoCheckpoints)

    async def __call__(self, job: Job, progress: JobProgress, /) -> None:
        """Re-chunk every version; raising fails the job."""
        step = self.checkpoints.step
        versions = await step("list the versions", partial(_versions, self.sources, job.library))
        await progress.report(done=0, total=len(versions))
        total = _VersionOutcome()
        failures: list[tuple[str, str, str]] = []
        for done, current in enumerate(versions, 1):
            tracker = _OneVersion(progress, current.ref, total)
            outcome = await step(
                f"re-chunk {current.ref}", partial(self._one, job, current, tracker)
            )
            total = total.plus(outcome)
            for problem in outcome.problems:
                await progress.problem(problem.path, problem.code, problem.reason)
            await progress.report(done=done, total=len(versions))
            await progress.chunking(chunked=total.chunked, reused=total.reused)
            await progress.parsing(parsed=total.parsed, taken=total.taken)
            if outcome.failure is not None:
                failures.append((current.ref, *outcome.failure))
        if failures:
            raise ReprocessFailedError(failures)

    async def _one(self, job: Job, current: ImportedRef, tracker: _OneVersion) -> _VersionOutcome:
        try:
            source = await self.sources.get(job.library)
            chunker = self.chunker.configured(source.chunking)
            copied = await self.copier.copy(
                job.library, current.ref, content_version=PARSER_VERSION
            )
        except StoredTextOutdatedError:
            return await _reimport(self.importer, job, current, tracker)
        except Exception as error:
            log.warning("re-chunking %s %s failed", job.library, current.ref, exc_info=True)
            return tracker.outcome((failure_code(error), _describe(error)))
        if copied is None:  # removed since the versions were listed: nothing to serve
            return tracker.outcome()
        try:
            await self._publish(job.library, current.ref, copied, source, chunker, tracker)
        except Exception as error:
            await _discard_shielded(self.versions, self.index, job.library, copied.manifest_id)
            log.warning("re-chunking %s %s failed", job.library, current.ref, exc_info=True)
            return tracker.outcome((failure_code(error), _describe(error)))
        except BaseException:
            await _discard_shielded(self.versions, self.index, job.library, copied.manifest_id)
            raise
        return tracker.outcome()

    async def _publish(
        self,
        library: str,
        ref: str,
        copied: CopiedVersion,
        source: ImportSource,
        chunker: Chunker,
        tracker: _OneVersion,
    ) -> None:
        """Re-tag and re-chunk the copy, index it, then activate it."""
        wanted = {
            a.path: StoredArticleTags(
                path=a.path, front_matter=a.front_matter, tags=a.tags
            ).retagged(source.tag_rules)
            for a in copied.articles
        }
        tagged = await self.tags.set_imported_tags(copied.manifest_id, wanted)
        blobs = list(dict.fromkeys(a.blob_sha for a in copied.articles))
        found: dict[str, tuple[ArticleChunk, ...]] = {}
        for start in range(0, len(blobs), KNOWN_BATCH):
            found |= await self.index.known(chunker.config_hash, blobs[start : start + KNOWN_BATCH])
        unknown: dict[str, ParsedArticle] = {}
        for article in copied.articles:
            if article.blob_sha not in found:
                unknown.setdefault(article.blob_sha, article.parsed())
        cut = await asyncio.to_thread(_cut, chunker, unknown)
        every = found | cut
        version = ImportedVersion(
            library=library,
            ref=ref,
            kind=copied.kind,
            commit_sha=copied.commit_sha,
            config_hash=chunker.config_hash,
            articles=tuple(
                ImportedArticle(
                    path=a.path,
                    blob_sha=a.blob_sha,
                    title=a.title,
                    tags=tagged.get(a.path, wanted[a.path]),
                    front_matter=dict(a.front_matter),
                    content=a.content,
                    chunks=every[a.blob_sha],
                )
                for a in copied.articles
            ),
            refresh=True,
        )
        await tracker.chunking(
            chunked=len(cut), reused=sum(a.blob_sha in found for a in copied.articles)
        )
        await tracker.parsing(parsed=0, taken=len(copied.articles))  # nothing parsed: all stored
        await self.index.index(copied.manifest_id, version)
        await _activate(self.versions, self.index, self.tag_locks, library, copied.manifest_id)


@dataclass(frozen=True, slots=True)
class ImportVersionUseCase:
    """Implements ``ports.driven.JobHandler`` for ``IMPORT_JOB``: a whole version or nothing.

    Fetch the pinned commit, read every selected file, parse those no earlier import stored (the
    same path, blob and ``PARSER_VERSION``: the others are taken from ``stored``, their tags
    derived again), chunk the blobs no earlier import chunked, store everything as a pending
    manifest, index its chunks, then activate it.
    Readers see the previous state until the last step; any failure (also a cancellation)
    discards what was stored, so a version never shows half of its articles.

    Images the articles reference (``![](img/a.png)``) are imported too: the ones the first
    checkout already holds are read from it, the others (outside the selected paths) are fetched
    in a second, literal-path checkout bounded by ``max_images_bytes``. Each is sniffed (PNG,
    JPEG, GIF, WebP, SVG), at most ``max_image_bytes`` big, and the version keeps at most
    ``MAX_IMAGES`` / ``max_images_bytes`` of them; any other image is listed as a problem and the
    import goes on.

    Images are held as bytes until stored, then again in the bridge's DTOs, the SQL parameters and
    the sorted manifest: budget about 8 x ``max_images_bytes`` per job at the peak, twice with
    two jobs at once (the 32 MiB default is a few hundred MiB).

    Memory: the selected text of the version is held in memory until it is stored, and again as
    chunks, as DTOs in the bridges and as SQL parameters, so a job needs several times
    ``max_import_bytes`` at its peak (and the worker runs two jobs at once). The budget makes the
    import fail with a clear error instead of the process being killed. Batched storing (the
    catalog would need an "append to a pending manifest" step) would lift the limit.
    """

    gateway: GitGateway
    chunker: Chunker
    sources: LibrarySources
    versions: VersionPublisher
    index: ChunkIndex
    vault: CredentialVault
    max_article_bytes: int = DEFAULT_MAX_ARTICLE_BYTES
    max_import_bytes: int = DEFAULT_MAX_IMPORT_BYTES
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES
    max_images_bytes: int = DEFAULT_MAX_IMAGES_BYTES
    refresh: bool = False
    renames: RenameSource | None = None
    """Where renames come from; without it none are detected. Never a reason to fail."""
    stored: StoredArticleSource | None = None
    """What earlier imports stored; without it every file is parsed."""
    checkpoints: Checkpoints = field(default_factory=_NoCheckpoints)
    """Makes the steps durable: a resumed import skips the files it had parsed and chunked."""
    batch_files: int = DEFAULT_IMPORT_BATCH_FILES
    """Files parsed and chunked per durable step."""
    tag_locks: TagLocks = field(default_factory=TagLocks)
    """Shared with ``TagArticleUseCase``: see there."""

    async def __call__(self, job: Job, progress: JobProgress, /) -> None:
        """Run the import, skipping the steps a run before a crash completed; raising fails it.

        The steps, in order: list the selected files; parse and chunk them ``batch_files`` at a
        time; read the README and the images; fetch the images outside the selection; detect
        renames; publish. Each one's result is a checkpoint, so a resumed import starts at the
        first step it had not finished. The commit is fetched only when a step needs its files
        (a resume that only has publishing left fetches nothing). Every step is safe to run
        again: it reads the pinned commit, and what it stores is keyed by content.
        """
        if job.version is None or job.commit_sha is None:
            raise ImportNotPinnedError
        source = await self.sources.get(job.library)
        # Unreadable or for another host: CredentialsRequiredError fails the job.
        credential = await self.vault.load(job.library, source.url.credential_scope)
        # A job queued without a kind is imported as a bare commit: the SHA is what is fetched.
        refs = _full_refs(job.ref_kind or RefKind.COMMIT, job.version)
        step = self.checkpoints.step
        # A step of its own: a resumed import cuts and labels its chunks with the config its
        # first run read, even if the library's chunking was edited in between.
        chunker = self.chunker.configured(
            await step("read the chunking settings", partial(_same, source.chunking))
        )
        try:
            async with AsyncExitStack() as stack:
                checkout = _Checkout(
                    lambda: self.gateway.fetch(
                        source.url,
                        str(job.commit_sha),
                        source.selection,
                        refs=refs,
                        credential=credential,
                    ),
                    stack,
                )
                paths = await step("list the selected files", lambda: _list(checkout, source))
                articles, wanted = await self._articles(
                    checkout, job.library, job.version, paths, source, chunker, progress
                )
                readme, context7, taken = await step(
                    "read the README, context7.json and the images",
                    lambda: self._assets(checkout, wanted),
                )
        except RepositoryAuthRequiredError as error:
            raise _anonymous(error, credential) from error
        if not articles:
            raise NoArticlesError
        for note in context7.notes():
            await progress.problem(CONTEXT7_FILE, ProblemCode.CONTEXT7, note)
        # After the fetch above has given its slot back: a second slot held while waiting for one
        # could deadlock two imports.
        images = await self._images(job, source, credential, taken, progress)
        renamed_from, renames = await step(
            "detect renames", lambda: self._renames(job, source, credential, refs, articles)
        )
        await step(
            "publish",
            partial(
                self._publish,
                ImportedVersion(
                    library=job.library,
                    ref=job.version,
                    kind=job.ref_kind or RefKind.COMMIT,
                    commit_sha=job.commit_sha,
                    config_hash=chunker.config_hash,
                    articles=tuple(articles),
                    images=images,
                    refresh=self.refresh,
                    renamed_from=renamed_from,
                    renames=renames,
                    origin=job.origin,
                ),
            ),
        )
        # Not a step: it never fails the import, reads what is imported now and replaces whole
        # maps, so running it again after a crash is the right thing to do.
        await self._renew_newer(job, job.ref_kind or RefKind.COMMIT, source, credential, refs)
        await self._describe(job.library, job.version, readme, context7)

    async def _describe(
        self, library: str, ref: str, readme: ReadmeSummary, context7: _Context7Read
    ) -> None:
        """Offer the version's text and rules; ``context7.json`` wins over the README (LIB-07).

        The version is live now: a catalog that cannot take them must not fail it. The catalog
        keeps a user's edits over both.
        """
        config = context7.config or Context7Config()
        try:
            await self.versions.describe(
                library=library,
                ref=ref,
                title=config.project_title or readme.title,
                description=config.description or readme.description,
                rules=config.rules,
            )
        except Exception:
            log.exception("could not apply the README of %s %s", library, ref)

    async def _publish(self, version: ImportedVersion) -> None:
        """Store the version as a pending manifest, index its chunks, then activate it.

        Any failure after the store discards what this run stored. What a run killed halfway
        left pending is discarded by the recovery hook before the job resumes.
        """
        manifest_id: str | None = None
        try:
            manifest_id = await self.versions.store(version)
            await self.index.index(manifest_id, version)
            await _activate(self.versions, self.index, self.tag_locks, version.library, manifest_id)
        except BaseException:
            await _discard_shielded(self.versions, self.index, version.library, manifest_id)
            raise

    async def _assets(
        self, checkout: _Checkout, wanted: Sequence[str]
    ) -> tuple[ReadmeSummary, _Context7Read, _ImageBudget]:
        """Read the root README and ``context7.json``, and the wanted images the checkout holds."""
        folder = await checkout.folder()
        readme, context7 = await asyncio.to_thread(_root_files, folder, self.max_article_bytes)
        taken = _ImageBudget(self.max_image_bytes, self.max_images_bytes)
        taken.absent = await asyncio.to_thread(_read_images, folder, wanted, taken)
        return readme, context7, taken

    async def _renames(
        self,
        job: Job,
        source: ImportSource,
        credential: Credential | None,
        refs: Sequence[str],
        articles: Sequence[ImportedArticle],
    ) -> tuple[str | None, tuple[GitRename, ...]]:
        """Find the renames to store with the version: ``(None, ())`` whatever goes wrong.

        A numeric tag gets what changed since the previous tag, also when a moved tag is
        re-imported; any other tag gets none. A branch (or commit) builds its map up: the
        renames its earlier syncs found are chained with this sync's (``compose_renames``). Old
        paths are filtered by the library's *current* selection, which may differ from the one
        the previous version was imported with.
        """
        if self.renames is None or job.version is None or job.commit_sha is None:
            return None, ()
        imported = await self._quietly(job, self.sources.imported_versions(job.library), [])
        before = previous_version(job.version, imported)
        if before is None or (before.ref == job.version and before.kind is RefKind.TAG):
            # A tag has no map of its own past: a re-imported (moved) tag without a numeric
            # order has nothing to be compared with, as when it was first imported.
            return None, ()
        unordered = is_unordered(job.version)
        earlier = (
            await self._quietly(job, self.sources.renames_of(job.library, job.version), [])
            if unordered
            else []
        )
        found = (
            []
            if before.commit_sha == job.commit_sha
            else await self._quietly(
                job,
                self.renames.renames(
                    source.url,
                    before.commit_sha,
                    job.commit_sha,
                    refs=[*refs, *_full_refs(before.kind, before.ref)],
                    credential=credential,
                ),
                [],
            )
        )
        paths = {article.path for article in articles}
        kept = [
            rename
            for rename in found
            if rename.new_path in paths
            and rename.old_path != rename.new_path
            and rename.old_path.isprintable()  # not a stray byte (a surrogate) or a control
            and source.selection.selects(rename.old_path)
        ]
        result = compose_renames(earlier, kept, paths) if unordered else tuple(kept)
        return (before.ref, result) if result else (None, ())

    async def _renew_newer(
        self,
        job: Job,
        kind: RefKind,
        source: ImportSource,
        credential: Credential | None,
        refs: Sequence[str],
    ) -> None:
        """Detect the renames of each newer version whose previous version this one now is.

        A version's map is found when it is imported, against the closest older version
        imported by then; an older one imported later is closer, so the newer map is found
        again against it (git rename detection only, no re-chunking), and manual tags follow
        the new map, chunks included. The version is live already: nothing here fails it, and
        a map git cannot give leaves the newer one as it was.
        """
        if self.renames is None or job.version is None or job.commit_sha is None:
            return
        listed = await self._quietly(job, self.sources.imported_versions(job.library), [])
        this = ImportedRef(ref=job.version, kind=kind, commit_sha=job.commit_sha)
        imported = [*(v for v in listed if v.ref != job.version), this]
        newer = [
            v
            for v in imported
            if v.ref != job.version and previous_version(v.ref, imported) == this
        ]
        for version in newer:
            found = await self._quietly(
                job,
                self.renames.renames(
                    source.url,
                    job.commit_sha,
                    version.commit_sha,
                    refs=[*_full_refs(version.kind, version.ref), *refs],
                    credential=credential,
                ),
                None,
            )
            if found is None:
                continue
            kept = [
                rename
                for rename in found
                if rename.old_path != rename.new_path
                and rename.old_path.isprintable()
                and source.selection.selects(rename.old_path)
            ]
            try:
                await self._replace_renames(job.library, version.ref, job.version, kept)
            except Exception:  # the newer version keeps its map; this import is done
                log.exception("could not renew the renames of %s %s", job.library, version.ref)

    async def _replace_renames(
        self, library: str, ref: str, from_ref: str, renames: Sequence[GitRename]
    ) -> None:
        """Store the map with the version ``ref`` serves; copy the tags it moves to the chunks."""
        async with self.tag_locks.of(library):
            retagged = await self.versions.replace_renames(
                library, ref, from_ref=from_ref, renames=renames
            )
            for manifest_id, articles in retagged.items():
                if articles:
                    await self.index.retag(manifest_id, articles)

    @staticmethod
    async def _quietly[T](job: Job, call: Awaitable[T], fallback: T) -> T:
        """Await ``call``; a failure (never a cancellation) is logged and ``fallback`` returned."""
        try:
            return await call
        except DomainError as error:  # expected: unreachable, auth, too large, ...
            log.warning("no renames known for %s %s: %s", job.library, job.version, type(error))
        except Exception:  # a missing rename map must never fail an import
            log.exception("no renames known for %s %s", job.library, job.version)
        return fallback

    async def _images(
        self,
        job: Job,
        source: ImportSource,
        credential: Credential | None,
        taken: _ImageBudget,
        progress: JobProgress,
    ) -> tuple[ImportedImage, ...]:
        """Add the images outside the selection (a step) to ``taken``'s; list the ones left out."""
        outside = await self.checkpoints.step(
            "fetch the images outside the selection",
            lambda: self._outside_images(job, source, credential, taken),
        )
        for skip in (*taken.skipped, *outside.skipped, *(_Missing(p) for p in outside.absent)):
            await progress.problem(
                skip.path.encode(errors="replace").decode(), skip.code, skip.reason
            )
        return (*taken.images, *outside.images)

    async def _outside_images(
        self,
        job: Job,
        source: ImportSource,
        credential: Credential | None,
        taken: _ImageBudget,
    ) -> _ImageBudget:
        """Fetch the images the first checkout lacked (outside the selection).

        Returns only what this step adds (its images, skips and the paths the commit lacks), on
        what is left of ``taken``'s budget: the images of the checkout are stored once, by the
        step that read them.
        """
        outside = _ImageBudget(taken.per_image, taken.total, count=taken.count, used=taken.used)
        if taken.absent and job.commit_sha and job.version:
            async with self.gateway.fetch_files(
                source.url,
                job.commit_sha,
                taken.absent,
                max_bytes=self.max_images_bytes,
                refs=_full_refs(job.ref_kind or RefKind.COMMIT, job.version),
                credential=credential,
            ) as folder:
                outside.absent = await asyncio.to_thread(
                    _read_images, folder, taken.absent, outside
                )
        else:
            outside.absent = list(taken.absent)
        return outside

    async def _articles(
        self,
        checkout: _Checkout,
        library: str,
        ref: str,
        paths: Sequence[str],
        source: ImportSource,
        chunker: Chunker,
        progress: JobProgress,
    ) -> tuple[list[ImportedArticle], list[str]]:
        """Return the articles and the image paths they reference (first-seen order).

        One durable step per ``batch_files`` files. What a step returns is all that later steps
        and the progress depend on, so a replayed step leaves the job as the first run did.
        """
        total, config_hash = len(paths), chunker.config_hash
        await progress.report(done=0, total=total)
        articles: list[_Article] = []
        chunks: dict[str, tuple[ArticleChunk, ...]] = {}
        stored: set[str] = set()
        used = taken = 0
        for start in range(0, total, self.batch_files):
            files = paths[start : start + self.batch_files]
            batch = await self.checkpoints.step(
                f"parse and chunk files {start + 1}-{start + len(files)}",
                partial(
                    self._batch,
                    checkout,
                    _BatchInput(
                        files,
                        start,
                        total,
                        used,
                        dict(chunks),
                        source,
                        config_hash,
                        chunker,
                        library,
                        ref,
                    ),
                    progress,
                ),
            )
            used = batch.used
            for path, code, reason in batch.problems:
                await progress.problem(path, code, reason)
            articles.extend(batch.articles)
            chunks |= {a.imported.blob_sha: a.imported.chunks for a in batch.articles}
            stored |= batch.stored
            taken += batch.taken
            await progress.report(done=start + len(files), total=total)
            await progress.chunking(
                chunked=len(chunks.keys() - stored),
                reused=sum(article.imported.blob_sha in stored for article in articles),
            )
            await progress.parsing(parsed=len(articles) - taken, taken=taken)
        wanted = list(dict.fromkeys(image for article in articles for image in article.images))
        if len(wanted) > MAX_WANTED_IMAGES:
            reason = f"{len(wanted) - MAX_WANTED_IMAGES} more images are referenced; not looked at"
            await progress.problem("", ProblemCode.TRUNCATED, reason)
        return [article.imported for article in articles], wanted[:MAX_WANTED_IMAGES]

    async def _batch(
        self, checkout: _Checkout, given: _BatchInput, progress: JobProgress
    ) -> _Batch:
        """Read some files; parse the ones not stored before, chunk the blobs not chunked before.

        A file an earlier import stored at the same path with the same parser is not parsed: its
        title, front matter and text are taken as stored, its tags derived again.
        """
        read, used = await self._read(await checkout.folder(), given, progress)
        files = [(path, sha) for path, sha, _ in (r for r in read if not isinstance(r, Skip))]
        found = await self._stored(given.library, given.ref, files)
        loaded: list[tuple[str, str, ParsedArticle]] = []
        problems: list[tuple[str, ProblemCode, str]] = []
        for path, result in zip(given.paths, read, strict=True):
            shown = path.encode(errors="replace").decode()
            if isinstance(result, Skip):
                problems.append((shown, result.code, result.reason))
                continue
            _, blob_sha, text = result
            parsed = found.get((path, blob_sha)) or parse_article(path, text)
            loaded.append((path, blob_sha, parsed))
            # The article is imported; the note is listed.
            problems.extend((shown, ProblemCode.FRONT_MATTER, note) for note in parsed.problems)
        known = given.known
        asked = [sha for sha in dict.fromkeys(sha for _, sha, _ in loaded) if sha not in known]
        chunked: dict[str, tuple[ArticleChunk, ...]] = {}
        for start in range(0, len(asked), KNOWN_BATCH):
            chunked |= await self.index.known(given.config_hash, asked[start : start + KNOWN_BATCH])
        unknown: dict[str, ParsedArticle] = {}
        for _, blob_sha, parsed in loaded:
            if blob_sha not in known and blob_sha not in chunked:
                unknown.setdefault(blob_sha, parsed)
        cut = await asyncio.to_thread(_cut, given.chunker, unknown)
        every = {**known, **chunked, **cut}
        rules = given.source.tag_rules
        return _Batch(
            articles=tuple(
                _Article(
                    imported=ImportedArticle(
                        path=path,
                        blob_sha=blob_sha,
                        title=parsed.title,
                        tags=article_tags(path, parsed.tags, rules),
                        front_matter=parsed.front_matter,
                        content=parsed.body,
                        chunks=every[blob_sha],
                    ),
                    images=parsed.images,
                )
                for path, blob_sha, parsed in loaded
            ),
            problems=tuple(problems),
            stored=frozenset(chunked),
            used=used,
            taken=sum((path, sha) in found for path, sha, _ in loaded),
        )

    async def _read(
        self, folder: Path, given: _BatchInput, progress: JobProgress
    ) -> tuple[list[tuple[str, str, str] | Skip], int]:
        """Read the batch's files: ``(path, blob SHA, text)`` or why skipped; the bytes used."""
        read: list[tuple[str, str, str] | Skip] = []
        used = given.used
        for offset, path in enumerate(given.paths, 1):
            result = await asyncio.to_thread(_load, folder, path, self.max_article_bytes)
            if isinstance(result, Skip):
                read.append(result)
            else:
                blob_sha, text, size = result
                used += size
                if used > self.max_import_bytes:
                    raise ImportTooLargeError(self.max_import_bytes)
                read.append((path, blob_sha, text))
            if offset < len(given.paths):  # the caller reports the last one, also on a replay
                await progress.report(done=given.first + offset, total=given.total)
        return read, used

    async def _stored(
        self, library: str, ref: str, files: Sequence[tuple[str, str]]
    ) -> dict[tuple[str, str], ParsedArticle]:
        """Rebuild the articles earlier imports stored for these files, by ``(path, blob SHA)``.

        A file the store cannot answer for, or whose rebuild needs a parse, is left out.
        """
        if self.stored is None:
            return {}
        found: dict[tuple[str, str], ParsedArticle] = {}
        for start in range(0, len(files), KNOWN_BATCH):
            batch = files[start : start + KNOWN_BATCH]
            for article in await self.stored.find(library, ref, PARSER_VERSION, batch):
                if (parsed := article.parsed()) is not None:
                    found[article.path, article.blob_sha] = parsed
        return found


async def _same[T](value: T) -> T:
    return value


def _cut(
    chunker: Chunker, articles: Mapping[str, ParsedArticle]
) -> dict[str, tuple[ArticleChunk, ...]]:
    return {sha: tuple(chunker.chunk(a)) for sha, a in articles.items()}


async def _activate(
    versions: VersionPublisher,
    index: ChunkIndex,
    tag_locks: TagLocks,
    library: str,
    manifest_id: str,
) -> None:
    """Give the manifest its library's manual tags, chunks included, then activate it.

    Last, so a tag set while the version was stored and indexed counts too.
    """
    async with tag_locks.of(library):
        tagged = await versions.apply_manual_tags(manifest_id)
        if tagged:
            await index.retag(manifest_id, tagged)
        await versions.activate(manifest_id)


async def _discard_shielded(
    versions: VersionPublisher, index: ChunkIndex, library: str, manifest_id: str | None
) -> None:
    """Discard what a failed publish left pending; the cancellation that got here cannot stop it.

    Run as a task of its own and shielded, so that the clean-up is not cut short. A failing
    clean-up is logged, never hides the cause.
    """

    async def discard() -> None:
        try:
            await _discard_pending(versions, index, library, manifest_id)
        except Exception:
            log.exception("could not discard the pending import of %s", library)

    cleanup = asyncio.ensure_future(discard())
    _cleanups.add(cleanup)
    cleanup.add_done_callback(_cleanups.discard)
    await asyncio.shield(cleanup)


def _full_refs(kind: RefKind, name: str) -> list[str]:
    prefix = {RefKind.TAG: "refs/tags/", RefKind.BRANCH: "refs/heads/"}.get(kind)
    return [] if prefix is None else [prefix + name]


KNOWN_BATCH = 500
MAX_WANTED_IMAGES = 4 * MAX_IMAGES  # distinct image paths looked for per version
_cleanups: set[asyncio.Future[None]] = set()  # the loop holds tasks weakly


@dataclass(slots=True)
class _Checkout:
    """The commit's files, fetched when a step first needs them, removed with ``stack``."""

    fetch: Callable[[], AbstractAsyncContextManager[Path]]
    stack: AsyncExitStack
    fetched: Path | None = None

    async def folder(self) -> Path:
        if self.fetched is None:
            self.fetched = await self.stack.enter_async_context(self.fetch())
        return self.fetched


async def _list(checkout: _Checkout, source: ImportSource) -> list[str]:
    # Only the walk of the checkout is `checkout_unreadable`; a fetch that fails on the disk
    # (full, out of file handles) fails as itself.
    folder = await checkout.folder()
    try:
        return await asyncio.to_thread(_selected_files, folder, source.selection)
    except OSError as error:
        raise CheckoutUnreadableError from error


@dataclass(frozen=True, slots=True)
class _BatchInput:
    """What one parse-and-chunk step needs, all of it fixed by the steps before it."""

    paths: Sequence[str]
    first: int
    """How many files the steps before this one took."""
    total: int
    used: int
    """Bytes of text taken by the steps before this one."""
    known: Mapping[str, tuple[ArticleChunk, ...]]
    """Chunks of the blobs the steps before this one took."""
    source: ImportSource
    config_hash: str
    chunker: Chunker
    library: str
    ref: str


@dataclass(frozen=True, slots=True)
class _Article:
    imported: ImportedArticle
    images: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Batch:
    """The durable result of one parse-and-chunk step."""

    articles: tuple[_Article, ...]
    problems: tuple[tuple[str, ProblemCode, str], ...]
    stored: frozenset[str]
    """Blobs whose chunks an earlier import had stored."""
    used: int
    taken: int = 0
    """Articles not parsed: taken as an earlier import had stored them."""


@dataclass(frozen=True, slots=True)
class DiscardInterruptedImportUseCase:
    """Implements ``ports.driven.RecoveryHook`` for ``IMPORT_JOB``."""

    versions: VersionPublisher
    index: ChunkIndex

    async def __call__(self, job: Job, /) -> None:
        """Drop what the interrupted run stored; a library has one running import at a time."""
        await _discard_pending(self.versions, self.index, job.library, None)


async def _discard_pending(
    versions: VersionPublisher, index: ChunkIndex, library: str, manifest_id: str | None
) -> None:
    """Delete the pending chunks, then the pending manifests (the order matters, see the port).

    Both are attempted whatever happens to the first; the first error is raised afterwards.
    """
    errors: list[Exception] = []
    for discard in (index.discard, versions.discard):
        try:
            await discard(manifest_id=manifest_id, library=library)
        except Exception as error:
            log.exception("discarding pending data of %s failed", library)
            errors.append(error)
    if errors:
        raise errors[0]


def _selected_files(folder: Path, selection: PathSelection) -> list[str]:
    """List the checked-out files the library takes, repository-relative, sorted.

    A folder that cannot be listed raises, so that a version is never published without it.
    """

    def fail(error: OSError) -> None:
        raise error

    found = []
    # symlinked folders are listed in `dirs`, not entered
    for root, dirs, files in os.walk(folder, onerror=fail):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            path = (Path(root) / name).relative_to(folder).as_posix()
            if selection.selects(path):
                found.append(path)
    return sorted(found)


def _full_refs(kind: RefKind, version: str) -> list[str]:
    """Return the full ref name to try when a server refuses a bare SHA (none for a commit)."""
    prefix = {RefKind.TAG: "refs/tags/", RefKind.BRANCH: "refs/heads/"}.get(kind)
    return [] if prefix is None else [prefix + version]


@dataclass(slots=True)
class _ImageBudget:
    """What the images of one version may still take; the images turned away, with why."""

    per_image: int
    total: int
    count: int = 0
    used: int = 0
    images: list[ImportedImage] = field(default_factory=list)
    skipped: list[Skip | _Missing] = field(default_factory=list)
    absent: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Missing:
    """The repository has no file at this path (at the commit)."""

    path: str
    code: ProblemCode = ProblemCode.MISSING_IMAGE
    reason: str = "no such file in the repository at this commit"


def _through_a_link(folder: Path, path: str) -> bool:
    """Whether any directory on the way to ``path`` is a symlink (it could lead out of ``folder``).

    ``_read`` only refuses a link as the last component. Git is run with ``core.symlinks=false``,
    so a real checkout holds none; this keeps a checkout that does from reading the host's files.
    """
    current = folder
    for part in path.split("/")[:-1]:
        current /= part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                return True
        except OSError:
            return False  # absent: the read reports it
    return False


def _read_images(folder: Path, paths: Sequence[str], budget: _ImageBudget) -> list[str]:
    """Read the images that exist in ``folder`` into ``budget``; return the paths it lacks.

    A file that is not a plain file, too big, not an allowed image by its content, or over the
    version's budget is turned away (``budget.skipped``) and the rest goes on. Content is
    hashed with git's blob rule, like articles.
    """
    absent: list[str] = []
    for path in paths:
        try:
            if _through_a_link(folder, path):
                budget.skipped.append(Skip(ProblemCode.NOT_A_FILE, "not a regular file", path))
                continue
            data = _read(folder / path, budget.per_image)
        except FileNotFoundError, NotADirectoryError:
            absent.append(path)
            continue
        except OSError:
            budget.skipped.append(Skip(ProblemCode.UNREADABLE, "unreadable", path))
            continue
        if isinstance(data, Skip):
            budget.skipped.append(replace(data, path=path))
        elif (kind := sniff_image(data)) is None:
            reason = "not a PNG, JPEG, GIF, WebP or SVG image"
            budget.skipped.append(Skip(ProblemCode.NOT_AN_IMAGE, reason, path))
        elif budget.count >= MAX_IMAGES or budget.used + len(data) > budget.total:
            reason = "the version's image budget is used up"
            budget.skipped.append(Skip(ProblemCode.IMAGE_BUDGET, reason, path))
        else:
            budget.count += 1
            budget.used += len(data)
            budget.images.append(
                ImportedImage(path=path, blob_sha=git_blob_sha(data), content_type=kind, data=data)
            )
    return absent


def _readme(folder: Path, limit: int) -> ReadmeSummary:
    """Summarize the root README (``README.md``, else ``README.mdx``); nothing if there is none.

    It is read whatever the path selection says (the git gateway always fetches it) and is as
    untrusted as any article. A README that is a symlink, not a plain file, too big or not
    UTF-8 counts as absent (the first of the two names that exists decides). This never raises:
    the summary is a nicety and must not fail an import whose articles are fine.
    """
    for name in ("README.md", "README.mdx"):
        try:
            data = _read(folder / name, limit)
            return ReadmeSummary() if isinstance(data, Skip) else readme_summary(data.decode())
        except FileNotFoundError:
            continue
        except Exception:
            log.exception("could not summarize the README of a checkout")
            return ReadmeSummary()
    return ReadmeSummary()


def _root_files(folder: Path, limit: int) -> tuple[ReadmeSummary, _Context7Read]:
    """Read the root README and ``context7.json`` of a checkout; never raises."""
    return _readme(folder, limit), _context7(folder)


@dataclass(frozen=True, slots=True)
class _Context7Read:
    """The root ``context7.json`` of a checkout: parsed, or why it is ignored, or neither."""

    config: Context7Config | None = None
    warning: str | None = None

    def notes(self) -> tuple[str, ...]:
        """Why the file is ignored, or what was left out of it."""
        return (self.warning,) if self.warning else (self.config.notes if self.config else ())


def _context7(folder: Path) -> _Context7Read:
    """Read and parse the root ``context7.json``; nothing if there is none. Never raises.

    Like the README it is read whatever the selection says and is untrusted. A file that is
    not a plain file, too big or not a valid ``context7.json`` gives a warning and is ignored.
    """
    try:
        data = _read(folder / CONTEXT7_FILE, CONTEXT7_MAX_BYTES)
        if isinstance(data, Skip):
            return _Context7Read(warning=str(InvalidContext7Error(data.reason)))
        return _Context7Read(config=parse_context7(data))
    except FileNotFoundError:
        return _Context7Read()
    except InvalidContext7Error as error:
        return _Context7Read(warning=str(error))
    except Exception:
        log.exception("could not read the context7.json of a checkout")
        return _Context7Read(warning=str(InvalidContext7Error("it could not be read")))


async def _fetch_context7(
    tree: RepositoryTree | None,
    repository: RepositoryUrl,
    resolved: ResolvedRef,
    credential: Credential | None,
    *,
    busy_raises: bool = False,
) -> _Context7Read:
    """Read only the root ``context7.json`` of the pinned commit; raises only when told to.

    The file is a pre-fill: whatever goes wrong (the remote, every preview slot busy for longer
    than a preview waits, the disk) is a warning and adding or previewing goes on without it,
    except that ``busy_raises`` lets ``PreviewBusyError`` through. Without a tree (a module
    built with no git) there is no file.
    """
    if tree is None:
        return _Context7Read()
    try:
        found = await tree.read_file(
            repository,
            resolved.commit_sha,
            CONTEXT7_FILE,
            max_bytes=CONTEXT7_MAX_BYTES,
            refs=_full_refs(resolved.kind, resolved.name),
            credential=credential,
        )
    except PreviewBusyError:
        if busy_raises:
            raise
        reason = "it was not read, every preview slot is busy; try again shortly"
    except DomainError as error:
        log.warning("could not fetch context7.json: %s", type(error).__name__)
        reason = f"it could not be fetched: {error}"
    except Exception:
        log.exception("could not read context7.json")
        reason = "it could not be read"
    else:
        return _context7_of(found)
    return _Context7Read(warning=str(InvalidContext7Error(reason)))


def _context7_of(found: FetchedFile) -> _Context7Read:
    if found.problem is not None:
        return _Context7Read(warning=str(InvalidContext7Error(found.problem)))
    if found.data is None:
        return _Context7Read()
    try:
        return _Context7Read(config=parse_context7(found.data))
    except InvalidContext7Error as error:
        return _Context7Read(warning=str(error))


@dataclass(frozen=True, slots=True)
class Skip:
    """Why a file is left out of the version (never echoes its content)."""

    code: ProblemCode
    reason: str
    path: str = ""


def _load(folder: Path, path: str, limit: int) -> tuple[str, str, int] | Skip:
    """Read and decode one file, or say why it is skipped.

    Returns the blob SHA, the text and the byte size. A file over ``limit`` bytes is not read
    at all. Anything that is not a plain file (a symlink could point outside the checkout) or not
    readable is skipped, as is text that no supported encoding decodes.
    The blob SHA is hashed from the checked-out bytes, which equals git's because the
    ``GitGateway`` must check files out verbatim (no eol or filter conversion).
    Chunk sets are reused by blob SHA, so changing ``_decode`` leaves already-imported blobs
    with their old text until they change; a UTF-8 BOM is stripped now (``utf-8-sig``), so
    blobs imported before that may still carry U+FEFF in their chunks.
    """
    try:
        path.encode()
    except UnicodeEncodeError:
        return Skip(ProblemCode.BAD_FILE_NAME, "file name is not valid UTF-8")
    try:
        data = _read(folder / path, limit)
    except OSError:
        return Skip(ProblemCode.UNREADABLE, "unreadable")
    if isinstance(data, Skip):
        return data
    text = _decode(data)
    if isinstance(text, Skip):
        return text
    return git_blob_sha(data), text, len(data)


# FF FE 00 00 is also a UTF-16-LE file starting with U+0000; UTF-32 is tried first, and a file
# that then fails to decode is reported undecodable, which is right for such a file anyway.
_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)
MAX_CONTROL_RATIO = 0.02


def _decode(data: bytes) -> str | Skip:
    """UTF-8, else UTF-16/32 announced by a BOM, else Windows-1252; NUL bytes mean binary.

    Windows-1252 stands in for Latin-1 (it is a superset where text lives); bytes it leaves
    undefined, or more than 2% control characters, make the file undecodable. Not detected:
    UTF-16/32 without a BOM (reported as binary, or imported as mojibake when it has no NULs),
    and other legacy charsets (CJK, Cyrillic) that happen to pass as Windows-1252. A real
    charset detector is not worth a dependency.
    """
    for bom, codec in _BOMS:
        if data.startswith(bom):
            try:
                return data.decode(codec)
            except UnicodeDecodeError:
                return Skip(ProblemCode.UNDECODABLE, _NOT_TEXT)
    if b"\0" in data:
        return Skip(ProblemCode.BINARY, "binary file")
    with suppress(UnicodeDecodeError):
        return data.decode("utf-8-sig")
    with suppress(UnicodeDecodeError):
        text = data.decode("cp1252")
        controls = sum(c < " " and c not in "\t\n\r\f" for c in text)
        if controls <= len(text) * MAX_CONTROL_RATIO:
            return text
    return Skip(ProblemCode.UNDECODABLE, _NOT_TEXT)


_NOT_TEXT = "not text in any supported encoding"


def _read(file: Path, limit: int) -> bytes | Skip:
    """Return the bytes of a plain file of up to ``limit`` bytes, else why it is skipped."""
    too_big = Skip(ProblemCode.TOO_LARGE, f"larger than {limit} bytes")
    not_a_file = Skip(ProblemCode.NOT_A_FILE, "not a regular file")
    info = file.lstat()
    if not stat.S_ISREG(info.st_mode):
        return not_a_file
    if info.st_size > limit:
        return too_big
    with _open_plain(file) as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):  # swapped since lstat
            return not_a_file
        data = handle.read(limit + 1)
    return data if len(data) <= limit else too_big


@contextmanager
def _open_plain(file: Path) -> Generator[BinaryIO]:
    """Open for reading without following a symlink; the descriptor is always closed.

    Yields:
        The binary file object.

    """
    fd = os.open(file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        handle = os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise
    with handle:
        yield handle


async def _refuse_while_importing(jobs: JobRepository, library: str, version: str | None) -> None:
    """Raise ``ImportInProgressError`` when an import of the library (or version) is unfinished.

    Check, then remove. An import queued in between can only come from a sync (E9-01) and is
    queued as a ``refresh`` job: it fails at store time if the version is gone, and a removal
    that comes after the store deletes its pending manifest, so it cannot re-create the version.
    An ``import`` job for a library that was removed fails at store time (no library).
    """
    # ponytail: loads all of the library's jobs; a "has unfinished jobs" query if that grows.
    for job in await jobs.list_for_library(library):
        if job.state in ACTIVE_JOB_STATES and (
            job.kind in LIBRARY_KINDS  # re-processes every version, this one too
            or (job.kind in IMPORT_KINDS and (version is None or job.version == version))
        ):
            raise ImportInProgressError(library, version)


async def _queue_collection(
    jobs: JobRepository, enqueue_job: EnqueueJob, removed: Removed
) -> str | None:
    """Queue the job that frees the content; the removal itself is done, so never raise.

    A collection already waiting for the library will see this removal too: reuse it.
    """
    try:
        for job in await jobs.list_for_library(removed.library):
            if job.kind == COLLECT_JOB and job.state is JobState.QUEUED:
                return job.id
        job = await enqueue_job(EnqueueJobCommand(kind=COLLECT_JOB, library=removed.library))
    except Exception:
        log.exception("could not queue the collection after removing %s", removed.library)
        return None
    return job.id


async def _forget_chunks(index: ChunkIndex, removed: Removed) -> None:
    """Drop the removed manifests' chunks now; if it fails the collection job sweeps them."""
    try:
        await index.remove(removed.manifest_ids)
    except Exception:
        log.exception("could not remove the chunks of %s", removed.library)


@dataclass(frozen=True, slots=True)
class TagArticleUseCase:
    """Implements ``ports.driving.TagArticle``.

    The catalog re-tags its manifests, then the chunk index gets the same tags. The library's
    lock (``locks``, shared with the importer) keeps that pair whole against an import that
    re-tags the manifest it is about to activate: otherwise the older of two writes could land
    last in the chunk index. One process runs the jobs and serves the API (``serve`` pins one
    worker), so a process lock is enough.
    """

    tags: ManualTagStore
    index: ChunkIndex
    locks: TagLocks

    async def __call__(self, command: TagArticleCommand) -> TaggedArticle:
        """Store the tags, then copy every touched article's tags onto its chunks."""
        async with self.locks.of(command.library):
            tagged = await self.tags.set_tags(command.library, command.path, command.tags)
            for manifest_id, articles in tagged.retagged.items():
                await self.index.retag(manifest_id, articles)
        return TaggedArticle(library=tagged.library, path=tagged.path, tags=list(tagged.tags))


@dataclass(frozen=True, slots=True)
class RemoveVersionUseCase:
    """Implements ``ports.driving.RemoveVersion``."""

    jobs: JobRepository
    removals: Removals
    index: ChunkIndex
    enqueue_job: EnqueueJob

    async def __call__(self, command: RemoveVersionCommand) -> RemovalResult:
        """Refuse during an import of the version, remove it from the catalog, then clean up."""
        library = command.library.lower()  # library IDs are stored lower-case
        await _refuse_while_importing(self.jobs, library, command.ref)
        removed = await self.removals.remove_version(library, command.ref)
        await self.jobs.delete_for(library, command.ref)  # its history is not a state any more
        await _forget_chunks(self.index, removed)
        return RemovalResult(
            library=removed.library,
            ref=removed.ref,
            default_version=removed.default_ref,
            collection_job_id=await _queue_collection(self.jobs, self.enqueue_job, removed),
        )


@dataclass(frozen=True, slots=True)
class RemoveLibraryUseCase:
    """Implements ``ports.driving.RemoveLibrary``."""

    jobs: JobRepository
    removals: Removals
    index: ChunkIndex
    enqueue_job: EnqueueJob
    vault: CredentialVault
    schedules: AutoSyncStore
    switch: ScheduleSwitch

    async def __call__(self, command: RemoveLibraryCommand) -> RemovalResult:
        """Refuse during any import of the library, remove it from the catalog, then clean up."""
        library = command.library.lower()
        await _refuse_while_importing(self.jobs, library, None)
        removed = await self.removals.remove_library(library)
        await self.jobs.delete_for(library)
        await self.vault.delete(library)  # the removed library's token or key goes with it
        await self.schedules.delete(library)  # and its scheduled check
        await _switch_to_need(self.schedules, self.switch)
        await _forget_chunks(self.index, removed)
        return RemovalResult(
            library=removed.library,
            ref=None,
            default_version=None,
            collection_job_id=await _queue_collection(self.jobs, self.enqueue_job, removed),
        )


@dataclass(frozen=True, slots=True)
class CollectGarbageUseCase:
    """Implements ``ports.driven.JobHandler`` for ``COLLECT_JOB``.

    Runs each domain's collector in order (the catalog first: retrieval keeps what the catalog
    still knows), then fails the job if any collector failed, after the others had their turn.
    Chunk IDs of collected manifests are not kept as tombstones yet: a stale ID older than the
    grace period answers ``not_found`` instead of ``stale_chunk`` (see docs/plan.md, E7-03).
    """

    collectors: Sequence[Collector]
    grace_seconds: int = DEFAULT_GRACE_SECONDS

    async def __call__(self, job: Job, progress: JobProgress, /) -> None:
        """Collect; raising fails the job."""
        errors: list[Exception] = []
        await progress.report(done=0, total=len(self.collectors))
        for done, collector in enumerate(self.collectors, 1):
            try:
                await collector.collect(grace_seconds=self.grace_seconds)
            except Exception as error:
                log.exception("collection for %s failed", job.library)
                errors.append(error)
            await progress.report(done=done, total=len(self.collectors))
        if errors:
            raise errors[0]


@dataclass(frozen=True, slots=True)
class GetAutoSyncUseCase:
    """Implements ``ports.driving.GetAutoSync``."""

    sources: LibrarySources
    schedules: AutoSyncStore

    async def __call__(self, query: GetAutoSyncQuery) -> AutoSyncOut:
        """Return the library's schedule; ``enabled`` false when it has none."""
        library = query.library.lower()
        await self.sources.get(library)  # an unknown library is not found
        found = await self.schedules.get(library)
        return AutoSyncOut.disabled(library) if found is None else AutoSyncOut.from_model(found)


@dataclass(frozen=True, slots=True)
class SetAutoSyncUseCase:
    """Implements ``ports.driving.SetAutoSync``."""

    sources: LibrarySources
    schedules: AutoSyncStore
    switch: ScheduleSwitch

    async def __call__(self, command: SetAutoSyncCommand) -> AutoSyncOut:
        """Store the schedule; the library is due at once, so the next tick checks it."""
        library = command.library.lower()
        await self.sources.get(library)
        auto_sync = AutoSync(
            library=library,
            tag_pattern=command.tag_pattern,
            keep_last=command.keep_last,
            interval_minutes=command.interval_minutes,
            sync_branches=command.sync_branches,
            revision=uuid.uuid4().hex,
        )
        await self.schedules.save(auto_sync)
        await self.switch.turn(on=True)
        return AutoSyncOut.from_model(auto_sync)


@dataclass(frozen=True, slots=True)
class DisableAutoSyncUseCase:
    """Implements ``ports.driving.DisableAutoSync``."""

    sources: LibrarySources
    schedules: AutoSyncStore
    switch: ScheduleSwitch

    async def __call__(self, command: DisableAutoSyncCommand) -> AutoSyncOut:
        """Forget the schedule; every version stays. The last one off stops the tick."""
        library = command.library.lower()
        await self.sources.get(library)
        await self.schedules.delete(library)
        await _switch_to_need(self.schedules, self.switch)
        return AutoSyncOut.disabled(library)


@dataclass(frozen=True, slots=True)
class SwitchScheduleUseCase:
    """Implements ``ports.driving.SwitchSchedule``."""

    schedules: AutoSyncStore
    switch: ScheduleSwitch

    async def __call__(self) -> None:
        """Tick only while some library has a schedule."""
        await _switch_to_need(self.schedules, self.switch)


async def _switch_to_need(schedules: AutoSyncStore, switch: ScheduleSwitch) -> None:
    await switch.turn(on=bool(await schedules.list_all()))


@dataclass(slots=True)
class _Tally:
    """What a tick did so far."""

    checked: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    def out(self) -> ScheduledChecks:
        return ScheduledChecks(checked=self.checked, imports=self.imports, removed=self.removed)


@dataclass(frozen=True, slots=True, kw_only=True)
class RunScheduledChecksUseCase:
    """Implements ``ports.driving.RunScheduledChecks``: one tick of the schedule (SYNC-02).

    The clock decides which libraries are due (``AutoSync.is_due``), so the schedule's own tick
    only needs to be finer than the shortest interval. Each due library is checked in turn:
    with a tag pattern the remote is asked for its tags and ``plan_auto_imports`` says what to
    queue (``auto`` imports, oldest first) and which ``auto`` versions to remove (through
    ``RemoveVersion``, which waits for nothing: a version being imported is left for the next
    check); with ``sync_branches`` the library is then re-synced by ``SyncLibrary`` from the
    same refs (listed once), which records its failures on the versions' jobs as a sync by hand
    does. What a check could not do is its ``last_error``; the check is recorded when it ends
    (compare-and-set: not over a schedule saved meanwhile), so a library that fails is tried
    again only after its interval. A schedule of a removed library is dropped, and the tick
    paused when none is left (``ScheduleSwitch``).
    """

    schedules: AutoSyncStore
    sources: LibrarySources
    remote: GitRemote
    vault: CredentialVault
    jobs: JobRepository
    clock: Clock
    enqueue_job: EnqueueJob
    sync_library: SyncLibraryFromRefs
    remove_version: RemoveVersion
    switch: ScheduleSwitch
    _running: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    async def __call__(self) -> ScheduledChecks:
        """Check every due library; a tick that meets one still running does nothing."""
        tally = _Tally()
        if self._running.locked():
            return tally.out()
        async with self._running:
            now = self.clock.now()
            for auto_sync in await self.schedules.list_all():
                if auto_sync.is_due(now):
                    await self._check_one(auto_sync, tally)
        return tally.out()

    async def _check_one(self, auto_sync: AutoSync, tally: _Tally) -> None:
        library = auto_sync.library
        try:
            error = await self._check(auto_sync, tally)
        except NotFoundError:  # the library was removed: so is its schedule
            await self.schedules.delete(library)
            await _switch_to_need(self.schedules, self.switch)
            return
        except Exception as raised:
            log.exception("the scheduled check of %s failed", library)
            error = _describe(raised)
        tally.checked.append(library)
        # Recorded only if nobody saved (or turned off) the schedule while it was checked.
        await self.schedules.record_check(auto_sync, auto_sync.checked(self.clock.now(), error))

    async def _check(self, auto_sync: AutoSync, tally: _Tally) -> str | None:
        library = auto_sync.library
        source = await self.sources.get(library)
        errors: list[str] = []
        refs: RemoteRefs | None = None
        if auto_sync.tag_pattern is not None:
            credential: Credential | None = None
            try:
                credential = await self.vault.load(library, source.url.credential_scope)
                refs = await self.remote.list_refs(source.url, credential=credential)
            except DomainError as raised:
                errors.append(f"tags not checked: {_anonymous(raised, credential)}")
            else:
                errors += await self._tags(auto_sync, ref_tips(refs), tally)
        if auto_sync.sync_branches:
            try:
                # The refs listed for the tags; without them (none, or the remote failed) the
                # sync asks itself, and records a failure on the versions' jobs.
                await self.sync_library(SyncLibraryCommand(library=library), refs=refs)
            except VersionImportingError:
                pass  # the branch is being imported already
            except DomainError as raised:  # also recorded on the versions' jobs
                errors.append(f"branches not synced: {raised}")
        return "; ".join(errors) or None

    async def _tags(
        self, auto_sync: AutoSync, tips: Sequence[ResolvedRef], tally: _Tally
    ) -> list[str]:
        library = auto_sync.library
        versions = await self.sources.imported_versions(library)
        jobs = await self.jobs.list_for_library(library)  # newest first
        held = _failed_tags(
            jobs,
            versions,
            now=self.clock.now(),
            interval=timedelta(minutes=auto_sync.interval_minutes),
        )
        plan = plan_auto_imports(auto_sync, tips, versions, failed=held)
        busy = _busy_refs(jobs)
        errors: list[str] = []
        for tip in plan.imports:
            if tip.name in busy:
                continue
            try:
                job = await _enqueue_import(self.enqueue_job, library, tip, VersionOrigin.AUTO)
            except VersionImportingError:
                continue  # queued by someone else meanwhile
            except DomainError as raised:
                errors.append(f"{tip.name!r} not queued: {raised}")
            else:
                tally.imports.append(job.id)
        for ref in plan.removals:
            try:
                await self.remove_version(RemoveVersionCommand(library=library, ref=ref))
            except ImportInProgressError, NotFoundError:
                continue  # being imported (tried at the next check), or already gone
            except DomainError as raised:
                errors.append(f"{ref!r} not removed: {raised}")
            else:
                tally.removed.append(f"{library}/{ref}")
        return errors


def _failed_tags(
    jobs: Sequence[Job], versions: Sequence[ImportedRef], *, now: datetime, interval: timedelta
) -> set[tuple[str, str]]:
    """Return (ref, commit) of the refs that are no version and are not to be imported now.

    A failure the same commit would meet again (``PERMANENT_IMPORT_FAILURES``) holds the tag
    back until it moves. An ``unexpected`` one (a bug, perhaps at that commit) backs off: after
    the n-th in a row at the same commit, the tag waits 2**(n-1) - 1 more check intervals, at
    most ``UNEXPECTED_BACKOFF_CAP``. Any other failure (an unreachable repository, a refused
    credential...) is tried at the next check.
    """
    have = {v.ref for v in versions}
    imports: dict[str, list[Job]] = {}
    for job in jobs:  # newest first
        if job.version and job.kind in IMPORT_KINDS:
            imports.setdefault(job.version, []).append(job)
    held: set[tuple[str, str]] = set()
    for ref, tried in imports.items():
        last = tried[0]
        if ref in have or last.state is not JobState.FAILED or not last.commit_sha:
            continue
        backing_off = (
            last.error_code == UNEXPECTED_ERROR
            and last.finished_at is not None
            and now < last.finished_at + _backoff(tried, interval)
        )
        if last.error_code in PERMANENT_IMPORT_FAILURES or backing_off:
            held.add((ref, last.commit_sha))
    return held


_MAX_DOUBLINGS = 16


def _backoff(tried: Sequence[Job], interval: timedelta) -> timedelta:
    """How long after its last failure a tag that keeps failing ``unexpected`` waits."""
    last = tried[0]
    in_a_row = 0
    for job in tried:  # newest first
        if (job.state, job.error_code, job.commit_sha) != (
            JobState.FAILED,
            UNEXPECTED_ERROR,
            last.commit_sha,
        ):
            break
        in_a_row += 1
    doublings = min(in_a_row - 1, _MAX_DOUBLINGS)
    return min(interval * (2**doublings - 1), UNEXPECTED_BACKOFF_CAP)
