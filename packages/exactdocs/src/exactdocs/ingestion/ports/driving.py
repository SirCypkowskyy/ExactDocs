"""Driving (primary) ports of ingestion: what the outside world may ask it to do."""

from collections.abc import Collection
from typing import Protocol

from exactdocs.ingestion.dtos import (
    AddedLibrary,
    AddedVersion,
    AddLibraryCommand,
    AddVersionCommand,
    AutoSyncOut,
    CheckedRepository,
    CheckRepositoryCommand,
    DisableAutoSyncCommand,
    EnqueueJobCommand,
    GetAutoSyncQuery,
    GetJobQuery,
    GetLibraryAccessQuery,
    JobList,
    JobSummary,
    LatestJobs,
    LibraryAccess,
    ListLibraryJobsQuery,
    ListRepositoryRefsQuery,
    PreviewRepositoryCommand,
    QueuedEmbedding,
    QueueEmbeddingCommand,
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
    SyncLibraryCommand,
    TagArticleCommand,
    TaggedArticle,
    UpdatedLibrarySettings,
    UpdateLibrarySettingsCommand,
)
from exactdocs.ingestion.models import RemoteRefs


class EnqueueJob(Protocol):
    """Queue a job; raises ``UnknownJobKindError`` when no handler is registered for its kind."""

    async def __call__(self, command: EnqueueJobCommand) -> JobSummary:
        """Run the use case."""
        ...


class GetJob(Protocol):
    """Fetch one job; raises ``JobNotFoundError`` when it does not exist."""

    async def __call__(self, query: GetJobQuery) -> JobSummary:
        """Run the use case."""
        ...


class GetLibraryAccess(Protocol):
    """Say whether a library is private (has a stored credential)."""

    async def __call__(self, query: GetLibraryAccessQuery) -> LibraryAccess:
        """Run the use case."""
        ...


class ListLibraryJobs(Protocol):
    """List a page of a library's jobs, newest first."""

    async def __call__(self, query: ListLibraryJobsQuery) -> JobList:
        """Run the use case."""
        ...


class ListLatestJobs(Protocol):
    """List the newest job of every (library, version)."""

    async def __call__(self) -> LatestJobs:
        """Run the use case."""
        ...


class RecoverJobs(Protocol):
    """On start: clean up after interrupted jobs and hand every queued job to the runner."""

    async def __call__(self, *, resuming: Collection[str] = ()) -> None:
        """Run the hook of each ``running`` job, queue it again, then submit the queued jobs.

        Jobs whose ID is in ``resuming`` are left as they are: the runner already has them and
        resumes them from their last durable step.
        """
        ...


class SubmitQueuedJobs(Protocol):
    """Hand every queued job to the runner again (it ignores the ones it already has)."""

    async def __call__(self) -> None:
        """Run the use case."""
        ...


class RunJob(Protocol):
    """Run one job to its end: a queued one, or one that was running when the app stopped."""

    async def __call__(self, job_id: str, /) -> None:
        """Do nothing for a job that is unknown or already finished.

        The caller makes sure that no other job of the library runs meanwhile. A job found
        ``running`` is resumed: its recovery hook runs, its progress starts over and its
        handler's completed durable steps (``Checkpoints``) are not done again.
        """
        ...


class RunNextJob(Protocol):
    """Run the next job that may run to its end, or do nothing."""

    async def __call__(self) -> bool:
        """Return whether a job ran (``False``: nothing was waiting)."""
        ...


class CheckRepository(Protocol):
    """Validate a pasted git URL and propose a library ID, saving nothing.

    Raises ``InvalidRepositoryUrlError``, ``LibraryIdTakenError`` (checked before any network
    traffic), ``NotAGitRepositoryError``, ``RepositoryUnreachableError`` or
    ``RepositoryAuthRequiredError``.
    """

    async def __call__(self, command: CheckRepositoryCommand) -> CheckedRepository:
        """Run the use case."""
        ...


class AddLibrary(Protocol):
    """Create a library, pin its ref to a commit and queue the import.

    Raises what ``CheckRepository`` raises, plus ``InvalidPathPatternError``, ``UnknownRefError``
    and ``AmbiguousRefError``. Nothing is stored unless all of it checks out.
    """

    async def __call__(self, command: AddLibraryCommand) -> AddedLibrary:
        """Run the use case."""
        ...


class AddVersion(Protocol):
    """Pin a ref of an existing library to a commit and queue its import.

    Raises ``NotFoundError`` for an unknown library, ``VersionExistsError`` when it already has
    that ref, and what ``AddLibrary`` raises for the ref. Nothing is queued unless all checks out.
    """

    async def __call__(self, command: AddVersionCommand) -> AddedVersion:
        """Run the use case."""
        ...


class ReimportVersion(Protocol):
    """Re-import a tag version at the commit the tag names now: the confirmation of ``tag_moved``.

    Raises ``NotFoundError`` for an unknown library or version, ``NotATagError`` for a branch or
    commit version, ``VersionImportingError`` when an import of it is queued or running,
    ``RefDeletedError`` when the tag is gone upstream, ``TagNotMovedError`` when it still names
    the commit the version serves, and what ``CheckRepository`` raises when the remote cannot be
    read. Nothing is queued unless all of it checks out; the version keeps serving until then.
    """

    async def __call__(self, command: ReimportVersionCommand) -> ReimportedVersion:
        """Run the use case."""
        ...


class ListRepositoryRefs(Protocol):
    """List a repository's branches and tags; raises what ``CheckRepository`` raises."""

    async def __call__(self, query: ListRepositoryRefsQuery) -> RepositoryRefs:
        """Run the use case."""
        ...


class PreviewRepository(Protocol):
    """List the files an import of (URL, ref, patterns) would take, importing nothing.

    Raises what ``AddLibrary`` raises, plus ``CommitUnavailableError`` and
    ``TreeTooLargeError`` from the tree fetch. Nothing is stored.
    """

    async def __call__(self, command: PreviewRepositoryCommand) -> RepositoryPreview:
        """Run the use case."""
        ...


class RemoveVersion(Protocol):
    """Remove a version from every surface and queue the job that frees its content.

    Raises ``LibraryNotFoundError`` / ``VersionNotFoundError`` (catalog) and
    ``ImportInProgressError`` when an import of that version is queued or running: removal
    refuses, it never cancels a job. Removing the last version leaves the library without
    versions; removing the default version moves the default to the next best one.
    """

    async def __call__(self, command: RemoveVersionCommand) -> RemovalResult:
        """Run the use case."""
        ...


class RemoveLibrary(Protocol):
    """Remove a library and all its versions, and queue the job that frees their content.

    Raises ``LibraryNotFoundError`` and ``ImportInProgressError`` when any import of the library
    is queued or running.
    """

    async def __call__(self, command: RemoveLibraryCommand) -> RemovalResult:
        """Run the use case."""
        ...


class SyncLibrary(Protocol):
    """Re-sync a library: queue an import for each branch version whose tip moved.

    Commits and tags that still name their commit are reported as pinned, a branch that did not
    move as up to date, a branch whose import is queued or running as importing; a branch or tag
    gone upstream (``ref_deleted``) or a tag that moved (``tag_moved``, re-imported only through
    ``ReimportVersion``) as failed, with the code on a failed job. Raises ``NotFoundError`` for
    an unknown library, ``VersionImportingError`` when an import is running and nothing could be
    queued, and ``SyncFailedError`` (``repo_unreachable`` or ``auth_failed``, plus the IDs of the
    failed jobs that record it) when the remote cannot be read: the versions keep what they served.
    """

    async def __call__(self, command: SyncLibraryCommand) -> SyncedLibrary:
        """Run the use case."""
        ...


class SyncLibraryFromRefs(Protocol):
    """``SyncLibrary``, optionally from the refs the remote advertised a moment ago.

    The scheduled check lists the refs for its tags and hands them on, so the remote is asked
    once; ``None`` asks it. ``SyncLibraryUseCase`` implements both ports.
    """

    async def __call__(
        self, command: SyncLibraryCommand, *, refs: RemoteRefs | None = None
    ) -> SyncedLibrary:
        """Run the use case."""
        ...


class TagArticle(Protocol):
    """Tag an article path by hand, for every version of its library (TAG-01).

    The tags replace the path's earlier manual tags (none removes them) and combine with the
    imported ones of the article at that path in each version, and of the article git saw it
    renamed to in later versions; later imports get them too. Listings, tag counts and search
    see them when this returns: the chunks' tag copies are refreshed, nothing is chunked again.

    Raises a not-found error for an unknown library and a validation error for a malformed path
    or a value that cannot be a tag.
    """

    async def __call__(self, command: TagArticleCommand) -> TaggedArticle:
        """Run the use case."""
        ...


class GetAutoSync(Protocol):
    """Read how a library is checked on its own (``enabled`` false when it is not).

    Raises ``NotFoundError`` for an unknown library.
    """

    async def __call__(self, query: GetAutoSyncQuery) -> AutoSyncOut:
        """Run the use case."""
        ...


class SetAutoSync(Protocol):
    """Turn on (or change) a library's scheduled check (SYNC-02); it runs at the next tick.

    Raises ``NotFoundError`` for an unknown library and ``InvalidAutoSyncError`` for a pattern,
    retention or interval that cannot be used. Nothing is imported or removed here.
    """

    async def __call__(self, command: SetAutoSyncCommand) -> AutoSyncOut:
        """Run the use case."""
        ...


class DisableAutoSync(Protocol):
    """Turn a library's scheduled check off; its versions, ``auto`` ones too, stay.

    Raises ``NotFoundError`` for an unknown library.
    """

    async def __call__(self, command: DisableAutoSyncCommand) -> AutoSyncOut:
        """Run the use case."""
        ...


class RunScheduledChecks(Protocol):
    """One tick of the schedule: check every library that is due (the clock decides).

    For each one, the remote is asked for its refs once: new matching tags are queued as
    ``auto`` imports, ``auto`` versions beyond ``keep_last`` removed, and with
    ``sync_branches`` the branches re-synced. What a library's check could not do is recorded on
    its schedule (``last_error``) and never stops the others. A tick that starts while another
    runs does nothing.
    """

    async def __call__(self) -> ScheduledChecks:
        """Run the use case."""
        ...


class SwitchSchedule(Protocol):
    """Turn the scheduled check's tick on when any library has a schedule, off otherwise."""

    async def __call__(self) -> None:
        """Run the use case."""
        ...


class UpdateLibrarySettings(Protocol):
    """Replace a library's paths, tag rules and chunking, then re-process every version in one job.

    Chunking left out keeps the stored one. Changed paths queue a ``reprocess`` job: each
    version is fetched again at the commit it serves (a branch is not synced) and re-imported
    with the new settings; a changed chunking queues a ``rechunk`` job, which cuts (and re-tags)
    each version's stored text again without fetching; only tag rules changed queue a ``retag``
    job, which re-tags each version from its stored articles without fetching. Either way each
    version switches to its new state at once and keeps serving the old one until then, or for
    good when its re-processing fails. Settings equal to the stored ones change nothing: they
    queue the library's widest failed re-processing again, else nothing. Raises a not-found
    error for an unknown library and ``InvalidPathPatternError`` / ``InvalidTagError`` /
    ``InvalidChunkingConfigError`` for invalid settings (nothing is stored).
    """

    async def __call__(self, command: UpdateLibrarySettingsCommand) -> UpdatedLibrarySettings:
        """Run the use case."""
        ...


class QueueEmbedding(Protocol):
    """Queue an ``embed`` job for each version the embedding model has not fully embedded.

    A version that already has a queued ``embed`` job gets no second one. Nothing is queued when
    no embedding model is configured, nor for a library with AI off. Called on start, after each
    import and when a job creates the space of a new model.
    """

    async def __call__(self, command: QueueEmbeddingCommand) -> QueuedEmbedding:
        """Run the use case.

        Args:
            command: Every library, or one.

        Returns:
            How many jobs were queued.
        """
        ...
