"""Driving (primary) ports of ingestion: what the outside world may ask it to do."""

from typing import Protocol

from exactdocs.ingestion.dtos import (
    AddedLibrary,
    AddedVersion,
    AddLibraryCommand,
    AddVersionCommand,
    CheckedRepository,
    CheckRepositoryCommand,
    EnqueueJobCommand,
    GetJobQuery,
    GetLibraryAccessQuery,
    JobList,
    JobSummary,
    LatestJobs,
    LibraryAccess,
    ListLibraryJobsQuery,
    ListRepositoryRefsQuery,
    PreviewRepositoryCommand,
    RemovalResult,
    RemoveLibraryCommand,
    RemoveVersionCommand,
    RepositoryPreview,
    RepositoryRefs,
    SyncedLibrary,
    SyncLibraryCommand,
)


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
    """On start: run each interrupted job's recovery hook, then queue it again."""

    async def __call__(self) -> None:
        """Run the use case."""
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


class ListRepositoryRefs(Protocol):
    """List a repository's branches and tags; raises what ``CheckRepository`` raises."""

    async def __call__(self, query: ListRepositoryRefsQuery) -> RepositoryRefs:
        """Run the use case."""
        ...


class PreviewRepository(Protocol):
    """List the files an import of (URL, ref, patterns) would take, importing nothing.

    Raises what ``AddLibrary`` raises, plus ``CommitUnavailableError`` and
    ``RepositoryTooLargeError`` from the tree fetch. Nothing is stored.
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

    Tags and commits are reported as pinned, a branch that did not move as up to date, a branch
    whose import is queued or running as importing. Raises ``NotFoundError`` for an unknown
    library, ``VersionImportingError`` when an import is running and nothing could be queued,
    and ``SyncFailedError`` (the remote's own error code, plus the IDs of the failed jobs that
    record it) when the remote cannot be read: the versions keep what they served.
    """

    async def __call__(self, command: SyncLibraryCommand) -> SyncedLibrary:
        """Run the use case."""
        ...
